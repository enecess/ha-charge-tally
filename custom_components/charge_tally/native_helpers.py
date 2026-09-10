"""Own native Integral/Utility Meter entries without borrowing their internals."""
import asyncio
from copy import deepcopy
from uuid import uuid4

from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN, PERIODS


class HelperSetupError(RuntimeError):
    """The point cannot yet use a required helper."""


class HelperRepairRequired(HelperSetupError):
    """An owned helper disappeared, changed, or has an uncertain creation."""


class NativeHelpers:
    """Persist ownership before accepting helpers as ready, serialized per owner.

    A durable, random creation token is set as the native config entry unique ID
    before creation. It recovers the ownership-save crash window without adopting
    same-name helpers. Native sensor unique IDs remain the helper entry IDs.
    """
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.helpers", atomic_writes=True)
        self._shared = hass.data.setdefault(f"{DOMAIN}_native_helpers", {}).setdefault(
            entry.entry_id, {"lock": asyncio.Lock(), "loaded": False, "points": {}},
        )

    async def _load(self):
        if not self._shared["loaded"]:
            data = await self._store.async_load()
            self._shared["points"] = data.get("points", {}) if data else {}
            self._shared["loaded"] = True

    async def _save(self):
        await self._store.async_save({"points": deepcopy(self._shared["points"])})

    async def async_ensure(self, point_id: str, point: dict, source_entity_id: str | None = None) -> dict:
        """Ensure Integral first; meters wait for runtime's normalized sensor ID."""
        async with self._shared["lock"]:
            await self._load()
            return await self._ensure(point_id, point, source_entity_id)

    async def _ensure(self, point_id, point, source_entity_id):
        record = self._shared["points"].setdefault(point_id, {"roles": {}})
        await self._recover_pending(record)
        # Check ownership before any mutation, even if this call removes a role.
        for owned in record["roles"].values():
            self._owned_entry(owned)
        record["point"] = deepcopy(point)
        if source_entity_id is not None:
            record["source_entity_id"] = source_entity_id
        await self._save()
        desired = {}
        if point["input_mode"] == "power":
            state = self.hass.states.get(point["power_entity"])
            unit = state.attributes.get("unit_of_measurement") if state else None
            if unit not in ("W", "kW"):
                raise HelperSetupError("invalid_power_source")
            payload = {"name": f"{point['name']} integral", "source": point["power_entity"],
                       "method": "left", "unit_time": "h", "max_sub_interval": {"seconds": 60}, "round": 6}
            if unit == "W":
                payload["unit_prefix"] = "k"
            desired["integral"] = ("integration", payload)
        periods = point.get("periods", list(PERIODS))
        if any(period not in PERIODS for period in periods):
            raise HelperSetupError("invalid_periods")
        for period in periods:
            role = f"utility_{period}"
            if source_entity_id is not None:
                desired[role] = ("utility_meter", {
                    "name": f"{point['name']} {period}", "source": source_entity_id, "cycle": period,
                    "offset": 0, "tariffs": [], "net_consumption": False, "delta_values": False,
                    "periodically_resetting": False, "always_available": False,
                })
            elif role in record["roles"]:
                owned = record["roles"][role]
                desired[role] = (owned["domain"], owned["payload"])
        for role in list(record["roles"]):
            owned = record["roles"][role]
            # Names may change without replacing measurement history.
            old_payload = {key: value for key, value in owned["payload"].items() if key != "name"}
            new_payload = {key: value for key, value in desired.get(role, (None, {}))[1].items() if key != "name"}
            if role not in desired or old_payload != new_payload:
                await self._remove_role(record, role)
        result = {"integral_entity_id": None, "utility_entities": {}}
        for role, (domain, payload) in desired.items():
            if role not in record["roles"]:
                await self._create(record, role, domain, payload)
            entity_id = await self._resolve(record["roles"][role])
            if role == "integral":
                result["integral_entity_id"] = entity_id
            else:
                result["utility_entities"][role.removeprefix("utility_")] = entity_id
        await self._save()
        return result

    def _owned_entry(self, owned):
        if not owned.get("entry_id"):
            raise HelperRepairRequired("uncertain_helper_creation")
        entry = self.hass.config_entries.async_get_entry(owned["entry_id"])
        if entry is None or entry.domain != owned["domain"]:
            raise HelperRepairRequired("missing_owned_helper")
        if entry.unique_id != owned.get("creation_token"):
            raise HelperRepairRequired("invalid_helper_ownership")
        if entry.disabled_by is not None:
            raise HelperRepairRequired("disabled_owned_helper")
        for key, value in owned["payload"].items():
            if key != "name" and entry.options.get(key) != value:
                raise HelperRepairRequired("changed_owned_helper")
        return entry

    async def _recover_pending(self, record):
        """Recover only exact tokens durably recorded before a native flow ran."""
        for role, owned in list(record["roles"].items()):
            if owned.get("entry_id"):
                continue
            token = owned.get("creation_token")
            if not isinstance(token, str) or not token.startswith(f"{DOMAIN}:{self.entry.entry_id}:"):
                raise HelperRepairRequired("uncertain_helper_creation")
            matches = [entry for entry in self.hass.config_entries.async_entries(owned["domain"])
                       if entry.unique_id == token]
            if len(matches) > 1:
                raise HelperRepairRequired("ambiguous_helper_ownership")
            if matches:
                owned["entry_id"] = matches[0].entry_id
                self._owned_entry(owned)
                owned["status"] = "created"
            else:
                self._abort_pending_flow(owned)
                del record["roles"][role]
            await self._save()

    def _abort_pending_flow(self, owned):
        for flow in self.hass.config_entries.flow.async_progress_by_handler(
            owned["domain"], match_context={"unique_id": owned["creation_token"]},
        ):
            self.hass.config_entries.flow.async_abort(flow["flow_id"])

    async def _create(self, record, role, domain, payload):
        owned = {"domain": domain, "payload": deepcopy(payload), "status": "creating",
                 "creation_token": f"{DOMAIN}:{self.entry.entry_id}:{uuid4().hex}"}
        record["roles"][role] = owned
        await self._save()
        try:
            result = await self.hass.config_entries.flow.async_init(
                domain, context={"source": "user", "unique_id": owned["creation_token"]}, data=payload,
            )
        except Exception as err:
            # The native flow may already have committed. Keep the token.
            self._abort_pending_flow(owned)
            raise HelperRepairRequired("uncertain_helper_creation") from err
        if result["type"] != FlowResultType.CREATE_ENTRY:
            if result["type"] == FlowResultType.FORM:
                self.hass.config_entries.flow.async_abort(result["flow_id"])
            del record["roles"][role]
            await self._save()
            raise HelperSetupError(f"{domain}_flow_failed")
        owned["entry_id"] = result["result"].entry_id
        owned["status"] = "created"
        # Save the ID immediately, including when native setup failed.
        await self._save()

    async def _resolve(self, owned):
        entry = self._owned_entry(owned)
        if entry.state == ConfigEntryState.NOT_LOADED:
            await self.hass.config_entries.async_setup(entry.entry_id)
        if entry.state != ConfigEntryState.LOADED:
            raise HelperSetupError(f"{owned['domain']}_not_loaded")
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id("sensor", owned["domain"], entry.entry_id)
        if entity_id is None:
            raise HelperRepairRequired("missing_owned_entity")
        entity = registry.async_get(entity_id)
        if entity.config_entry_id != entry.entry_id or entity.disabled_by is not None:
            raise HelperRepairRequired("disabled_owned_entity")
        owned["registry_id"] = entity.id
        owned["status"] = "ready"
        return entity_id

    async def _remove_role(self, record, role):
        owned = record["roles"][role]
        entry_id = owned.get("entry_id")
        if entry_id is None:
            raise HelperRepairRequired("uncertain_helper_creation")
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is not None:
            if entry.domain != owned["domain"]:
                raise HelperRepairRequired("invalid_helper_ownership")
            result = await self.hass.config_entries.async_remove(entry_id)
            if result.get("require_restart"):
                raise HelperSetupError("helper_removal_requires_restart")
        del record["roles"][role]
        await self._save()

    async def async_remove(self, point_id):
        """Remove only explicitly owned native entries, never input entities."""
        async with self._shared["lock"]:
            await self._load()
            record = self._shared["points"].get(point_id)
            if record is None:
                return
            await self._recover_pending(record)
            for role in list(record["roles"]):
                await self._remove_role(record, role)
            del self._shared["points"][point_id]
            await self._save()

    async def async_repair(self, point_id):
        """Explicitly recreate missing/altered owned helpers from saved config."""
        async with self._shared["lock"]:
            await self._load()
            record = self._shared["points"].get(point_id)
            if record is None:
                raise HelperRepairRequired("unknown_point")
            await self._recover_pending(record)
            for role, owned in list(record["roles"].items()):
                try:
                    await self._resolve(owned)
                except HelperRepairRequired:
                    await self._remove_role(record, role)
                except HelperSetupError:
                    entry = self._owned_entry(owned)
                    if not await self.hass.config_entries.async_reload(entry.entry_id):
                        raise
            return await self._ensure(point_id, record["point"], record.get("source_entity_id"))
