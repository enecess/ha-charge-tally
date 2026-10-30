"""HA event snapshots, native helper lifecycle, and serialized worker access."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from functools import partial
from typing import TYPE_CHECKING

from homeassistant.components import persistent_notification
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_state_report_event,
    async_track_utc_time_change,
)
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util

from .accounting import instant
from .archive import archive_ids
from .core.units import energy_kwh, power_w
from .history import HistorySource
from .native_helpers import HelperSetupError, NativeHelpers
from .runtime_store import RuntimeStore, required_roles

if TYPE_CHECKING:
    from . import ChargeTallyConfigEntry

_LOGGER = logging.getLogger(__name__)


class Runtime:
    def __init__(self, hass: HomeAssistant, entry: ChargeTallyConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self.configured_currency = entry.data["currency"]
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="charge_tally_ledger"
        )
        self._lock = asyncio.Lock()
        self._config_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._gate = asyncio.Event()
        self._gate.set()
        self._closed = False
        self._closing = False
        self._store = None
        self._tasks = set()
        self._unsubs = []
        self._timers = {}
        self._timer_deadlines = {}
        self._helpers = NativeHelpers(hass, entry)
        self.history = HistorySource(hass)
        self._helper_results = {}
        self._errors = {}
        self.points = {}
        self.snapshot = {
            "currency": entry.data["currency"],
            "identities": [],
            "points": [],
            "records": [],
            "summary": {},
            "revision": 0,
        }
        self.update_signal = "charge_tally_update_" + entry.entry_id
        self.config_signal = "charge_tally_config_" + entry.entry_id
        self.path = hass.config.path("charge_tally", "ledger.sqlite3")
        self._revision = 0
        self._period_unsub = None
        self._registry_unsub = None
        self._core_config_unsub = None
        self._stop_unsub = None

    async def _worker(self, function, *args):
        return await self.hass.loop.run_in_executor(
            self.executor, partial(function, *args)
        )

    async def _apply(self, method, *args, authorize=None):
        while True:
            await self._gate.wait()
            async with self._lock:
                if not self._gate.is_set():
                    continue
                if self._closed:
                    raise ValueError("Runtime is closed")
                if authorize is not None:
                    authorize()
                arguments = args
                if method in ("command", "public_command") and args[0] == "start":
                    arguments = (
                        *args,
                        self._measurement_available(args[1]["point_id"]),
                    )
                if method in ("command", "public_command") and args[0] == "end":
                    point_id = next(
                        (
                            record["point_id"]
                            for record in self.snapshot["records"]
                            if record["id"] == args[1]["record_id"]
                        ),
                        None,
                    )
                    arguments = (*args, self._low_power_available(point_id))
                result, snapshot = await self._worker(
                    self._store.apply, method, *arguments
                )
                self._publish(snapshot)
                return result

    def _measurement_available(self, point_id):
        """Check current HA state even when its change event has not run yet."""
        point = self.points.get(point_id)
        if point is None:
            return False
        entity_id = (
            self._helper_results.get(point_id, {}).get("integral_entity_id")
            if point["input_mode"] == "power"
            else point.get("energy_entity")
        )
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.attributes.get("state_class") not in (
            "total",
            "total_increasing",
        ):
            return False
        try:
            energy_kwh(state.state, state.attributes.get("unit_of_measurement"))
            if point["input_mode"] == "power":
                power = self.hass.states.get(point["power_entity"])
                if power is None:
                    return False
                power_w(power.state, power.attributes.get("unit_of_measurement"))
        except (ValueError, TypeError):
            return False
        return True

    def _low_power_available(self, point_id):
        """Reject cached low evidence when a newer HA event is still queued."""
        point = self.points.get(point_id)
        if point is None or not self._measurement_available(point_id):
            return False
        entity = point.get("power_entity")
        state = self.hass.states.get(entity) if entity else None
        if state is None:
            return False
        try:
            return power_w(
                state.state, state.attributes.get("unit_of_measurement")
            ) < Decimal(str(point.get("detection", {}).get("end_w", 0)))
        except (ValueError, TypeError):
            return False

    def _publish(self, snapshot):
        self._revision += 1
        self._decorate(snapshot)
        self.snapshot = snapshot
        async_dispatcher_send(self.hass, self.update_signal)
        self._schedule_timers()

    def _decorate(self, snapshot):
        snapshot["revision"] = self._revision
        registry = er.async_get(self.hass)
        for point in snapshot["points"]:
            point["utility_entities"] = self._helper_results.get(point["id"], {}).get(
                "utility_entities", {}
            )
            point["error"] = self._errors.get(point["id"])
            point["entity_id"] = registry.async_get_entity_id(
                "sensor",
                "charge_tally",
                self.entry.entry_id + ":" + point["id"] + ":energy",
            )
            if point["error"]:
                point["quality"] = sorted(set(point["quality"]) | {"helper_error"})
                point["available"] = False

    async def async_start(self):
        from .nfc_manager import NfcManager

        self.nfc = NfcManager(self.hass, self.entry, runtime_lock=self._lock)
        await self.nfc.async_load()
        self._store = await self._worker(
            RuntimeStore,
            self.path,
            self.entry.data["currency"],
            self.hass.config.time_zone,
        )
        await self.async_refresh_config(finish_helpers=False)

        @callback
        def core_config_changed(event):
            if "time_zone" in event.data:
                self._queue(
                    self._async_change_timezone(
                        event.data["time_zone"], event.time_fired
                    )
                )

        self._core_config_unsub = self.hass.bus.async_listen(
            EVENT_CORE_CONFIG_UPDATE, core_config_changed
        )

        @callback
        def minute(now):
            self._queue(self._apply("maintenance", now))

        self._period_unsub = async_track_utc_time_change(self.hass, minute, second=0)

        @callback
        def registry_changed(event):
            owned = {
                entity
                for result in self._helper_results.values()
                for entity in [
                    result.get("integral_entity_id"),
                    *result.get("utility_entities", {}).values(),
                ]
            }
            owned.update(point.get("entity_id") for point in self.snapshot["points"])
            if event.data.get("entity_id") in owned:
                self._queue(self.async_refresh_config())

        self._registry_unsub = self.hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, registry_changed
        )

        async def stopping(event):
            await self.async_close()

        self._stop_unsub = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, stopping
        )

    def _config(self):
        points, identities = {}, {}
        for subentry in self.entry.subentries.values():
            target = points if subentry.subentry_type == "point" else identities
            target[subentry.subentry_id] = deepcopy(dict(subentry.data))
        return points, identities

    async def _async_change_timezone(self, timezone, at):
        async with self._config_lock:
            if not self._closing:
                changes = await self._apply("change_timezone", timezone, at)
                await self._async_notify_timezone_changes(changes)

    async def _async_notify_timezone_changes(self, changes):
        if not changes:
            return
        translations = await async_get_translations(
            self.hass, self.hass.config.language, "issues", {"charge_tally"}
        )
        prefix = "component.charge_tally.issues.tou_timezone_changed."
        persistent_notification.async_create(
            self.hass,
            translations[prefix + "description"].format(
                points="\n".join(
                    f"- {change['name']}: {change['old_timezone']} → {change['new_timezone']}"
                    for change in changes
                ),
                timezone=changes[0]["new_timezone"],
            ),
            title=translations[prefix + "title"],
            notification_id="charge_tally_timezone_" + self.entry.entry_id,
        )

    async def async_refresh_config(self, *, finish_helpers=True):
        async with self._config_lock:
            if not self._closing:
                await self._refresh_config(finish_helpers=finish_helpers)

    async def _refresh_config(self, *, finish_helpers=True):
        points, identities = self._config()
        old_points = self.points
        old_sources = self._sources()
        removed = set(self.points) - set(points)
        changes = await self._apply(
            "configure",
            points,
            identities,
            dt_util.utcnow(),
            self.hass.config.time_zone,
        )
        await self._async_notify_timezone_changes(changes)
        self.points = points
        for point_id in removed:
            from homeassistant.helpers import issue_registry as ir

            ir.async_delete_issue(
                self.hass, "charge_tally", self.entry.entry_id + ":" + point_id
            )
            try:
                await self._helpers.async_remove(point_id)
            except (ValueError, OSError, HelperSetupError) as err:
                _LOGGER.warning(
                    "Could not remove owned helpers for %s: %s", point_id, err
                )
            self._helper_results.pop(point_id, None)
            self._errors.pop(point_id, None)
        for point_id, point in points.items():
            try:
                self._helper_results[point_id] = await self._helpers.async_ensure(
                    point_id, point
                )
                self._errors.pop(point_id, None)
            except (ValueError, OSError, HelperSetupError) as err:
                self._errors[point_id] = str(err)
        await self._bind_sources()
        self._subscribe()
        async_dispatcher_send(self.hass, self.config_signal)
        if finish_helpers:
            await self.async_finish_helpers()
        targets = {
            (point_id, role)
            for entity, pairs in self._sources().items()
            for point_id, role in pairs
            if (point_id, role) not in old_sources.get(entity, [])
            or (
                role == "price"
                and old_points.get(point_id, {}).get("price")
                != points[point_id]["price"]
            )
            or (
                role == "power"
                and old_points.get(point_id, {}).get("detection")
                != points[point_id].get("detection")
            )
        }
        await self._initial_observations(targets)

    async def async_finish_helpers(self):
        registry = er.async_get(self.hass)
        for point_id, point in self.points.items():
            entity_id = registry.async_get_entity_id(
                "sensor",
                "charge_tally",
                self.entry.entry_id + ":" + point_id + ":energy",
            )
            if entity_id:
                try:
                    self._helper_results[point_id] = await self._helpers.async_ensure(
                        point_id, point, entity_id
                    )
                    self._errors.pop(point_id, None)
                except (ValueError, OSError, HelperSetupError) as err:
                    self._errors[point_id] = str(err)
        await self._bind_sources()
        self._subscribe()
        await self._apply("snapshot")
        self._update_issues()

    async def _bind_sources(self):
        bindings = {}
        for entity, pairs in self._sources().items():
            for point_id, role in pairs:
                bindings.setdefault(point_id, {})[role] = entity
        await self._apply("bind_sources", bindings, self._errors, dt_util.utcnow())

    def _update_issues(self):
        from homeassistant.helpers import issue_registry as ir

        for point_id in self.points:
            issue_id = self.entry.entry_id + ":" + point_id
            if point_id in self._errors:
                ir.async_create_issue(
                    self.hass,
                    "charge_tally",
                    issue_id,
                    is_fixable=True,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="helper_repair",
                    translation_placeholders={
                        "name": self.points[point_id]["name"],
                        "error": self._errors[point_id],
                    },
                    data={"entry_id": self.entry.entry_id, "point_id": point_id},
                )
            else:
                ir.async_delete_issue(self.hass, "charge_tally", issue_id)

    def _sources(self):
        result = {}
        for point_id, point in self.points.items():
            energy = (
                self._helper_results.get(point_id, {}).get("integral_entity_id")
                if point["input_mode"] == "power"
                else point.get("energy_entity")
            )
            for role, entity_id in (
                ("energy", energy),
                (
                    "power",
                    point.get("power_entity")
                    if point["input_mode"] != "energy"
                    else None,
                ),
                (
                    "price",
                    point["price"].get("entity_id")
                    if point["price"]["mode"] == "dynamic"
                    else None,
                ),
            ):
                if entity_id:
                    result.setdefault(entity_id, []).append((point_id, role))
        return result

    @staticmethod
    def _observation(state, at, entity_id=None):
        return {
            "entity_id": entity_id or (state.entity_id if state else None),
            "at": at.isoformat(),
            "value": state.state if state else None,
            "unit": state.attributes.get("unit_of_measurement") if state else None,
            "state_class": state.attributes.get("state_class") if state else None,
        }

    def _subscribe(self):
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        sources = self._sources()
        if not sources:
            return

        @callback
        def changed(event):
            at = event.data.get("last_reported", event.time_fired)
            observation = self._observation(
                event.data.get("new_state"), at, event.data["entity_id"]
            )
            for point_id, role in sources.get(event.data["entity_id"], []):
                self._queue(self._handle_observation(point_id, role, observation))

        self._unsubs.extend(
            (
                async_track_state_change_event(self.hass, list(sources), changed),
                async_track_state_report_event(self.hass, list(sources), changed),
            )
        )

    def _queue(self, coroutine):
        if self._closing:
            coroutine.close()
            return

        async def run():
            try:
                await coroutine
            except Exception:
                _LOGGER.exception("Charge Tally queued operation failed")

        task = self.hass.async_create_task(run(), "charge_tally_event")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle_observation(self, point_id, role, data):
        gap = await self._apply("observe", point_id, role, data)
        if gap:
            await self.async_recover_history(
                point_id, instant(gap["start"]), instant(gap["end"])
            )

    async def _initial_observations(self, targets):
        # Prices precede energy so the first measured interval has a valid anchor.
        items = [
            (
                point,
                role,
                {
                    **self._observation(
                        self.hass.states.get(entity), dt_util.utcnow(), entity
                    ),
                    "detection_evidence": False,
                },
            )
            for entity, pairs in self._sources().items()
            for point, role in pairs
            if (point, role) in targets
        ]
        for point_id, role, data in sorted(
            items, key=lambda item: {"price": 0, "energy": 1, "power": 2}[item[1]]
        ):
            await self._handle_observation(point_id, role, data)

    def _schedule_timers(self):
        if self._closed or self._closing:
            return
        desired = {}
        for point in self.snapshot["points"]:
            if point.get("unavailable_deadline"):
                desired[("outage", point["id"])] = instant(
                    point["unavailable_deadline"]
                )
            if not point.get("candidate"):
                continue
            config = self.points.get(point["id"], {}).get("detection", {})
            duration = config.get(
                "start_seconds" if point["status"] == "pending_start" else "end_seconds"
            )
            if duration is None:
                continue
            deadline = instant(point["candidate"]) + timedelta(seconds=float(duration))
            desired[point["id"]] = deadline
        for point_id in list(self._timers):
            if self._timer_deadlines.get(point_id) != desired.get(point_id):
                self._timers.pop(point_id)()
                self._timer_deadlines.pop(point_id, None)
        for point_id, deadline in desired.items():
            if point_id in self._timers:
                continue

            @callback
            def timer(now, point_id=point_id):
                if isinstance(point_id, tuple):
                    self._queue(self._handle_unavailable_timeout(point_id[1], now))
                    return
                entity = self.points.get(point_id, {}).get("power_entity")
                observation = self._observation(
                    self.hass.states.get(entity), now, entity
                )
                observation["detection_evidence"] = False
                self._queue(self._handle_observation(point_id, "power", observation))

            self._timers[point_id] = async_track_point_in_utc_time(
                self.hass, timer, deadline
            )
            self._timer_deadlines[point_id] = deadline

    async def _handle_unavailable_timeout(self, point_id, now):
        point = next(
            (point for point in self.snapshot["points"] if point["id"] == point_id),
            None,
        )
        if point is None or not point["active_record"]:
            return
        roles = required_roles(self.points[point_id], point["active_record"]["source"])
        observations = []
        for entity_id, bindings in self._sources().items():
            for id_, role in bindings:
                if id_ == point_id and role in roles:
                    state = self.hass.states.get(entity_id)
                    observations.append(
                        (
                            role,
                            {
                                **self._observation(
                                    state,
                                    state.last_reported if state else now,
                                    entity_id,
                                ),
                                "detection_evidence": False,
                            },
                        )
                    )
        for role, observation in sorted(observations, key=lambda item: item[1]["at"]):
            await self._handle_observation(point_id, role, observation)
        await self._apply("expire_unavailable", point_id, now)

    async def async_config_guard(self, point_id, old_data, new_data):
        return await self._apply("guard", point_id)

    def _check_currency_runtime(self):
        if self._closing or self._closed or self._store is None:
            raise ValueError("runtime_unavailable")

    def _has_configured_points(self):
        return any(
            sub.subentry_type == "point" for sub in self.entry.subentries.values()
        )

    async def async_currency_change_allowed(self):
        self._check_currency_runtime()
        if self._has_configured_points():
            return False
        allowed = await self._read(self._store.ledger.currency_change_allowed)
        self._check_currency_runtime()
        return allowed and not self._has_configured_points()

    async def async_change_currency(self, currency, expected_currency):
        """Serialize rebinding with accounting and reject concurrent point creation."""
        async with self._config_lock:
            await self._gate.wait()
            async with self._lock:
                self._check_currency_runtime()
                if self.entry.data["currency"] != expected_currency:
                    raise ValueError("config_changed")
                if self._has_configured_points():
                    raise ValueError("currency_locked")
                if currency == expected_currency:
                    return
                change = self.hass.async_create_task(
                    self._worker(
                        self._store.change_currency, currency, expected_currency
                    ),
                )
                try:
                    # A cancelled flow must still wait for the SQLite write before rollback.
                    await asyncio.shield(change)
                    self._check_currency_runtime()
                    if self._has_configured_points():
                        raise ValueError("currency_locked")
                    if self.entry.data["currency"] != expected_currency:
                        raise ValueError("config_changed")
                    self.hass.config_entries.async_update_entry(
                        self.entry,
                        data={**self.entry.data, "currency": currency},
                    )
                except BaseException:
                    try:
                        await change
                    except Exception:
                        pass
                    else:
                        await self._worker(
                            self._store.change_currency, expected_currency, currency
                        )
                    raise

    async def async_snapshot(self, point_ids=None):
        if point_ids is not None:
            await self._gate.wait()
            if self._closed:
                raise ValueError("Runtime is closed")
        result = (
            deepcopy(self.snapshot)
            if point_ids is None
            or (
                point_ids
                and set(point_ids)
                == {
                    point["id"]
                    for point in self.snapshot["points"]
                    + self.snapshot.get("archived_points", [])
                }
            )
            else await self._read(self._store.snapshot, point_ids)
        )
        self._decorate(result)
        registry = er.async_get(self.hass)
        for point in result["points"]:
            entity_id = registry.async_get_entity_id(
                "select",
                "charge_tally",
                self.entry.entry_id + ":" + point["id"] + ":identity",
            )
            anchor = registry.async_get(entity_id) if entity_id else None
            point["identity_entity_id"] = (
                entity_id
                if anchor
                and anchor.config_entry_id == self.entry.entry_id
                and anchor.config_subentry_id == point["id"]
                and not anchor.disabled
                else None
            )
        return result

    def _archive_configuration(
        self, kind=None, object_id=None, target_identity_id=None
    ):
        self._check_currency_runtime()
        points, identities = self._config()
        configured = points if kind == "point" else identities
        if object_id is not None and any(
            id_ in configured or id_ == "unassigned" for id_ in archive_ids(object_id)
        ):
            raise ValueError("archive_configured")
        if target_identity_id is not None and target_identity_id != "unassigned":
            target = identities.get(target_identity_id)
            if target is None or not target.get("enabled", True):
                raise ValueError("archive_target")
        return points, identities

    async def _archive_read(
        self, method, kind=None, object_id=None, target_identity_id=None
    ):
        self._check_currency_runtime()
        async with self._config_lock:
            while True:
                await self._gate.wait()
                async with self._lock:
                    if not self._gate.is_set():
                        continue
                    points, identities = self._archive_configuration(
                        kind, object_id, target_identity_id
                    )
                    args = (
                        (points, identities)
                        if kind is None
                        else (kind, object_id, points, identities, target_identity_id)
                    )
                    result = await self._worker(getattr(self._store, method), *args)
                    latest = self._archive_configuration(
                        kind, object_id, target_identity_id
                    )
                    if latest != (points, identities):
                        continue
                    return result

    async def async_archive_catalog(self):
        return await self._archive_read("archive_catalog")

    async def async_archive_preview(self, kind, object_id, target_identity_id=None):
        return await self._archive_read(
            "archive_preview", kind, object_id, target_identity_id
        )

    @staticmethod
    async def _archive_settle(task):
        """Drain an already dispatched worker before releasing serialization."""
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        return task.result()

    async def async_archive_delete(
        self, kind, object_id, fingerprint, target_identity_id=None
    ):
        self._check_currency_runtime()
        async with self._config_lock:
            while True:
                await self._gate.wait()
                async with self._lock:
                    if not self._gate.is_set():
                        continue
                    points, identities = self._archive_configuration(
                        kind, object_id, target_identity_id
                    )
                    prepare = asyncio.create_task(
                        self._worker(
                            self._store.archive_prepare,
                            kind,
                            object_id,
                            fingerprint,
                            points,
                            identities,
                            target_identity_id,
                        )
                    )
                    try:
                        result, snapshot = await asyncio.shield(prepare)
                        _, latest_identities = self._archive_configuration(
                            kind, object_id, target_identity_id
                        )
                        if target_identity_id not in (None, "unassigned") and (
                            identities.get(target_identity_id)
                            != latest_identities.get(target_identity_id)
                        ):
                            raise ValueError("archive_stale")
                    except BaseException:
                        try:
                            await self._archive_settle(prepare)
                        except BaseException:
                            pass
                        rollback = asyncio.create_task(
                            self._worker(self._store.archive_finish, False)
                        )
                        await self._archive_settle(rollback)
                        raise
                    # Live configuration validation is the linearization point.
                    # No await separates validation from dispatching the commit.
                    commit = self.hass.loop.run_in_executor(
                        self.executor, partial(self._store.archive_finish, True)
                    )
                    await self._archive_settle(commit)
                    self._publish(snapshot)
                    return result

    async def _read(self, function, *args):
        await self._gate.wait()
        async with self._lock:
            if self._closed:
                raise ValueError("Runtime is closed")
            return await self._worker(function, *args)

    async def async_query(self, command, payload, *, point_ids=None):
        """The API supplies an already authorized point allowlist separately."""
        return await self._read(self._store.query, command, payload, point_ids)

    async def async_api_metadata(self, kind, key):
        return await self._read(
            self._store.ledger.get_checkpoint, "api_" + kind + ":" + key
        )

    async def async_bind_preview(self, token, principal, point_id, expected_revision):
        return await self._apply(
            "bind_preview", token, principal, point_id, expected_revision
        )

    async def async_public_command(self, command, payload, principal, authorize):
        from .record_views import record_view

        result = await self._apply(
            "public_command",
            command,
            payload,
            principal,
            dt_util.utcnow(),
            authorize=authorize,
        )
        return record_view(result)

    async def async_select_identity(self, point_id, identity_id, *, authorize=None):
        """Select through the same queue, rechecking references at execution time."""
        from .api import anchor_for

        def guard():
            if self._closing or self._closed:
                raise ValueError("runtime_unavailable")
            if authorize is not None:
                authorize()
            anchor = anchor_for(self, point_id)
            state = self.hass.states.get(anchor) if anchor else None
            if state is None or state.state in ("unavailable", "unknown"):
                raise ValueError("invalid_reference")
            identity = self.entry.subentries.get(identity_id)
            if identity_id != "unassigned" and (
                identity is None
                or identity.subentry_type != "identity"
                or not identity.data.get("enabled", True)
            ):
                raise ValueError("invalid_reference")

        return await self._apply(
            "command",
            "select_identity",
            {"point_id": point_id, "identity_id": identity_id},
            dt_util.utcnow(),
            authorize=guard,
        )

    async def async_command(self, command, payload):
        if command == "preview" and "energy_kwh" not in payload:
            data = dict(payload)
            if data.get("record_id"):
                detail = await self._apply(
                    "command",
                    "record",
                    {"record_id": data["record_id"]},
                    dt_util.utcnow(),
                )
                existing = detail["record"]
                if not any(k in data for k in ("start", "end", "point_id")):
                    return await self._apply(
                        "command", command, payload, dt_util.utcnow()
                    )
                data = {**existing, **data}
            await self.async_recover_history(
                data["point_id"], instant(data["start"]), instant(data["end"])
            )
        if command == "repair":
            point_id = payload["point_id"]
            if point_id not in self.points:
                raise ValueError("Unknown current point")
            self._helper_results[point_id] = await self._helpers.async_repair(point_id)
            await self.async_refresh_config()
            return {"point_id": point_id, "repaired": point_id not in self._errors}
        if command == "start" and payload.get("point_id") in self._errors:
            raise ValueError("Repair the point helpers before starting")
        result = await self._apply("command", command, payload, dt_util.utcnow())
        if command == "set_detection":
            subentry = self.entry.subentries[payload["point_id"]]
            data = deepcopy(dict(subentry.data))
            data["detection"] = {
                **data.get("detection", {}),
                "enabled": bool(payload["enabled"]),
            }
            self.hass.config_entries.async_update_subentry(
                self.entry, subentry, data=data
            )
            await self.async_refresh_config()
        return result

    async def async_recover_history(self, point_id, start, end):
        point = self.points.get(point_id)
        if point is None:
            return
        missing = await self._apply("history_needed", point_id, start, end)
        if not missing:
            return
        entity_id = (
            self._helper_results.get(point_id, {}).get("integral_entity_id")
            if point["input_mode"] == "power"
            else point.get("energy_entity")
        )
        if not entity_id:
            return
        intervals = await self.history.async_intervals(
            entity_id,
            start,
            end,
            point.get("resetting", True),
            point.get("max_gap_seconds", 600),
        )
        historical_prices = None
        if intervals and point["price"]["mode"] == "dynamic":
            historical_prices = await self.history.async_prices(
                point["price"]["entity_id"],
                min(instant(i["start"]) for i in intervals),
                max(instant(i["end"]) for i in intervals),
                self.entry.data["currency"],
                point["price"]["unit"],
            )
        await self._apply("import_history", point_id, intervals, historical_prices)

    async def async_pre_backup(self):
        async with self._lock:
            if self._closed:
                return
            self._gate.clear()
            try:
                await self._worker(
                    self._store.ledger.backup,
                    self.hass.config.path("charge_tally", "ledger.backup.sqlite3"),
                )
            except BaseException:
                self._gate.set()
                raise

    @callback
    def async_post_backup(self):
        self._gate.set()

    async def async_close(self):
        async with self._close_lock:
            await self._close()

    async def _close(self):
        if self._closed:
            return
        self._closing = True
        if hasattr(self, "nfc"):
            await self.nfc.async_close()
        self._gate.set()
        # Let an active refresh finish before removing the subscriptions it creates.
        async with self._config_lock:
            pass
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._period_unsub:
            self._period_unsub()
            self._period_unsub = None
        if self._registry_unsub:
            self._registry_unsub()
            self._registry_unsub = None
        if self._core_config_unsub:
            self._core_config_unsub()
            self._core_config_unsub = None
        if self._stop_unsub:
            self._stop_unsub()
            self._stop_unsub = None
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()
        if self._tasks:
            await asyncio.gather(*self._tasks)
        async with self._lock:
            self._closed = True
            if self._store:
                await self._worker(self._store.ledger.close)
        self.executor.shutdown(wait=False)
