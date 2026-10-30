"""Own NFC rule metadata without writing or executing HA automations."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from copy import deepcopy
from uuid import uuid4

from homeassistant.components.tag import TAG_DATA
from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.collection import CHANGE_REMOVED
from homeassistant.helpers.storage import Store
from homeassistant.util.json import load_json

from .nfc_rules import Catalog, compile_automation, execution_config, validate_draft


def same_config(left, right):
    """Missing and empty configurations are different ownership states."""
    if left is None or right is None:
        return left is right
    return execution_config(left) == execution_config(right)


class NfcManager:
    """Persist prepared operations before exposing an applied rule version."""

    def __init__(self, hass, entry, *, runtime_lock):
        self.hass, self.entry = hass, entry
        self.store = Store(hass, 1, f"charge_tally.nfc.{entry.entry_id}")
        self._runtime_lock = runtime_lock
        self._mutation_lock = asyncio.Lock()
        self._data = {"rules": {}, "receipts": {}, "tag_epochs": {}}
        self._closed = False
        self._tag_unsub = None
        self._component_unsub = None
        self._invalid_tags = set()

    async def async_load(self):
        data = await self.store.async_load()
        if data is not None:
            if not isinstance(data, dict) or set(data) != {
                "rules",
                "receipts",
                "tag_epochs",
            }:
                raise ValueError("invalid_storage")
            self._data = data
        self._attach_tags()

        @callback
        def component_loaded(event):
            if event.data.get("component") == "tag":
                self._attach_tags()

        self._component_unsub = self.hass.bus.async_listen(
            EVENT_COMPONENT_LOADED, component_loaded
        )

    @callback
    def _attach_tags(self):
        if not self._closed and self._tag_unsub is None:
            collection = self.hass.data.get(TAG_DATA)
            if collection is not None:
                self._tag_unsub = collection.async_add_listener(self._tag_changed)

    async def _tag_changed(self, change_type, item_id, config):
        if self._closed or change_type != CHANGE_REMOVED:
            return
        if not any(
            version and version.get("draft") and version["draft"]["tag_id"] == item_id
            for rule in self._data["rules"].values()
            for version in (rule["applied"], rule["pending"])
        ):
            return
        # HA may resurrect the same registry ID when this physical tag is scanned.
        self._invalid_tags.add(item_id)
        async with self._mutation_lock, self._runtime_lock:
            if self._closed:
                return
            data = deepcopy(self._data)
            data["tag_epochs"][item_id] = data["tag_epochs"].get(item_id, 0) + 1
            await self._save(data)
            self._invalid_tags.discard(item_id)

    def _check_open(self):
        if self._closed:
            raise ValueError("runtime_unavailable")

    def _catalog(self) -> Catalog:
        self._check_open()
        self._attach_tags()
        registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        devices = device_registry.devices
        # Older HA versions expose a mapping rather than an entry collection.
        if isinstance(devices, Mapping):
            devices = devices.values()
        points, identities = (
            [],
            [{"id": "unassigned", "name": "Unassigned", "active": True}],
        )
        for sub in self.entry.subentries.values():
            item = {
                "id": sub.subentry_id,
                "name": sub.data["name"],
                "active": sub.data.get("enabled", True),
            }
            if sub.subentry_type == "point":
                points.append(item)
            elif sub.subentry_type == "identity":
                identities.append(item)
        collection = self.hass.data.get(TAG_DATA)
        tags = []
        for item in collection.async_items() if collection else []:
            id_ = item["id"]
            entity_id = registry.async_get_entity_id("tag", "tag", id_)
            entity = registry.async_get(entity_id) if entity_id else None
            tags.append(
                {
                    "id": id_,
                    "name": (entity.name or entity.original_name or id_)
                    if entity
                    else item.get("name") or id_,
                }
            )
        return {
            "points": points,
            "identities": identities,
            "tags": tags,
            "devices": [
                {
                    "id": device.id,
                    "name": device.name_by_user or device.name or device.id,
                    "active": device.disabled_by is None,
                }
                for device in devices
            ],
        }

    async def async_catalog(self) -> Catalog:
        return self._catalog()

    def _validate_version(self, version):
        catalog = self._catalog()
        draft = validate_draft(version["draft"], catalog)
        tag_id = draft["tag_id"]
        if tag_id in self._invalid_tags or version["tag_epoch"] != self._data[
            "tag_epochs"
        ].get(tag_id, 0):
            raise ValueError("invalid_reference")
        return draft

    async def async_list(self):
        self._check_open()
        return deepcopy(list(self._data["rules"].values()))

    def _rule(self, rule_id):
        self._check_open()
        rule = self._data["rules"].get(rule_id)
        if rule is None:
            raise ValueError("rule_missing")
        return rule

    async def _save(self, data):
        await self.store.async_save(data)
        # Store may log write failures without raising; verify the file directly.
        try:
            persisted = await self.hass.async_add_executor_job(
                load_json, self.store.path
            )
        except HomeAssistantError as err:
            raise OSError("nfc_storage_save_failed") from err
        if persisted != {
            "version": self.store.version,
            "minor_version": self.store.minor_version,
            "key": self.store.key,
            "data": data,
        }:
            raise OSError("nfc_storage_save_failed")
        self._data = data

    def _copy(self, draft):
        from .nfc_text import automation_copy

        catalog = self._catalog()
        point = next(
            p["name"] for p in catalog["points"] if p["id"] == draft["point_id"]
        )
        tag = next(t["name"] for t in catalog["tags"] if t["id"] == draft["tag_id"])
        return automation_copy(self.hass.config.language, point, tag)

    async def async_prepare(
        self, kind, rule_id, draft, expected_revision, operation_id, *, authorize=None
    ):
        if kind not in {"create", "update", "restore", "recreate", "delete"}:
            raise ValueError("invalid_request")
        intent = [kind, rule_id, draft, expected_revision]
        async with self._mutation_lock, self._runtime_lock:
            self._check_open()
            if authorize is not None:
                authorize()
            receipt = self._data["receipts"].get(operation_id)
            if receipt:
                if receipt["intent"] != intent or receipt.get("cancelled"):
                    raise ValueError("conflict")
                return deepcopy(receipt["prepared"])
            if kind == "create":
                if rule_id is not None or expected_revision is not None:
                    raise ValueError("invalid_request")
                id_ = uuid4().hex
                rule = {
                    "rule_id": id_,
                    "automation_id": f"charge_tally_nfc_{self.entry.entry_id}_{id_}",
                    "revision": 0,
                    "applied": None,
                    "pending": None,
                    "deleting": False,
                }
            else:
                rule = deepcopy(self._rule(rule_id))
                if rule["pending"] is not None and not (
                    kind == "restore"
                    and rule["applied"] is not None
                    and not rule["deleting"]
                ):
                    raise ValueError("pending")
                if (
                    type(expected_revision) is not int
                    or expected_revision != rule["revision"]
                ):
                    raise ValueError("conflict")
                id_ = rule_id
            applied = rule["applied"]
            if kind in {"restore", "recreate"} and draft is None:
                draft = applied["draft"]
            if kind != "delete":
                draft = validate_draft(draft, self._catalog())
                for existing in self._data["rules"].values():
                    if existing["rule_id"] == id_:
                        continue
                    versions = [existing["applied"], existing["pending"]]
                    if any(
                        v
                        and v.get("draft")
                        and (v["draft"]["tag_id"], v["draft"]["point_id"])
                        == (draft["tag_id"], draft["point_id"])
                        for v in versions
                    ):
                        raise ValueError("duplicate_rule")
            version = (
                max(
                    applied["version"] if applied else 0,
                    rule["pending"]["version"] if rule["pending"] else 0,
                )
                + 1
            )
            prepared = {
                "operation_id": operation_id,
                "rule_id": id_,
                "revision": rule["revision"] + 1,
                "automation_id": rule["automation_id"],
                "kind": kind,
                "expected_config": applied["automation_config"] if applied else None,
                "desired_config": None
                if kind == "delete"
                else compile_automation(
                    id_, rule["automation_id"], draft, version, self._copy(draft)
                ),
                "draft": deepcopy(draft),
                "version": version,
                "tag_epoch": self._data["tag_epochs"].get(draft["tag_id"], 0)
                if kind != "delete"
                else 0,
            }
            data = deepcopy(self._data)
            if rule["pending"]:
                data["receipts"][rule["pending"]["operation_id"]]["cancelled"] = True
            rule.update(
                revision=prepared["revision"],
                pending=prepared,
                deleting=kind == "delete",
            )
            data["rules"][id_] = rule
            data["receipts"][operation_id] = {
                "intent": deepcopy(intent),
                "prepared": prepared,
            }
            await self._save(data)
            return deepcopy(prepared)

    async def async_inspect(self, rule_id, observed_config):
        rule = self._rule(rule_id)
        applied, pending = rule["applied"], rule["pending"]
        status = "synced"
        if observed_config is None:
            status = "missing"
        elif not any(
            config is not None and same_config(observed_config, config)
            for config in (
                applied["automation_config"] if applied else None,
                pending["desired_config"] if pending else None,
            )
        ):
            status = "external"
        elif pending:
            status = "pending"
        if status not in {"external", "missing"}:
            try:
                self._validate_version(pending or applied)
            except ValueError:
                status = "invalid"
        if pending and observed_config is None and applied is None:
            status = "pending"
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(
            "automation", "automation", rule["automation_id"]
        )
        state = self.hass.states.get(entity_id) if entity_id else None
        return {
            "config_status": status,
            "runtime_status": {"on": "enabled", "off": "paused"}.get(
                state.state if state else None, "unavailable"
            ),
            "automation_entity_id": entity_id,
            "pending_state": (
                "applied"
                if same_config(observed_config, pending["desired_config"])
                else "unwritten"
                if same_config(observed_config, pending["expected_config"])
                else "conflict"
            )
            if pending
            else None,
        }

    async def async_confirm(self, operation_id, observed_config, *, authorize=None):
        async with self._mutation_lock, self._runtime_lock:
            self._check_open()
            if authorize is not None:
                authorize()
            receipt = self._data["receipts"].get(operation_id)
            if not receipt or receipt.get("cancelled"):
                raise ValueError("conflict")
            prepared = receipt["prepared"]
            if not same_config(observed_config, prepared["desired_config"]):
                raise ValueError("conflict")
            if "result" in receipt:
                return deepcopy(receipt["result"])
            rule = self._rule(prepared["rule_id"])
            if rule["pending"] != prepared:
                raise ValueError("conflict")
            data = deepcopy(self._data)
            if prepared["kind"] == "delete":
                data["rules"].pop(rule["rule_id"])
                result = None
            else:
                # Acknowledge the verified native write even if a reference vanished.
                # Execution validates references independently and remains blocked.
                result = deepcopy(rule)
                result.update(
                    applied={
                        "version": prepared["version"],
                        "draft": prepared["draft"],
                        "automation_config": deepcopy(observed_config),
                        "tag_epoch": prepared["tag_epoch"],
                    },
                    pending=None,
                    revision=rule["revision"] + 1,
                )
                data["rules"][rule["rule_id"]] = result
            data["receipts"][operation_id]["result"] = result
            await self._save(data)
            return deepcopy(result)

    async def async_cancel(self, operation_id, observed_config, *, authorize=None):
        async with self._mutation_lock, self._runtime_lock:
            self._check_open()
            if authorize is not None:
                authorize()
            receipt = self._data["receipts"].get(operation_id)
            if not receipt or "result" in receipt:
                raise ValueError("conflict")
            prepared = receipt["prepared"]
            cancellable = (
                observed_config is not None
                if prepared["kind"] == "delete"
                else prepared["kind"] in {"create", "update"}
                and same_config(observed_config, prepared["expected_config"])
            )
            if not cancellable:
                raise ValueError("conflict")
            rule = self._rule(prepared["rule_id"])
            if rule["pending"] != prepared:
                raise ValueError("conflict")
            data = deepcopy(self._data)
            if rule["applied"] is None:
                data["rules"].pop(rule["rule_id"])
                result = None
            else:
                result = deepcopy(rule)
                result.update(
                    pending=None, deleting=False, revision=rule["revision"] + 1
                )
                data["rules"][rule["rule_id"]] = result
            data["receipts"][operation_id]["cancelled"] = True
            await self._save(data)
            return result

    def assert_selection(self, rule_id, rule_version, point_id, identity_id):
        rule = self._rule(rule_id)
        applied = rule["applied"]
        if rule["deleting"] or not applied or applied["version"] != rule_version:
            raise ValueError("not_applied")
        draft = self._validate_version(applied)
        identities = {item["identity_id"] for item in draft["device_bindings"]}
        identities.add(draft["default_identity_id"])
        if point_id != draft["point_id"] or identity_id not in identities:
            raise ValueError("invalid_reference")

    async def async_close(self):
        self._closed = True
        if self._tag_unsub:
            self._tag_unsub()
            self._tag_unsub = None
        if self._component_unsub:
            self._component_unsub()
            self._component_unsub = None
