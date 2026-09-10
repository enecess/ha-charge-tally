"""HA event snapshots, native helper lifecycle, and serialized worker access."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from functools import partial
import logging

from homeassistant.core import callback
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_utc_time, async_track_state_change_event, async_track_state_report_event, async_track_utc_time_change
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .accounting import instant
from .native_helpers import NativeHelpers, HelperSetupError
from .runtime_store import RuntimeStore
from .history import HistorySource

_LOGGER = logging.getLogger(__name__)


class Runtime:
    def __init__(self, hass, entry):
        self.hass, self.entry = hass, entry
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="charge_tally_ledger")
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
        self.snapshot = {"currency": entry.data["currency"], "identities": [], "points": [], "records": [], "summary": {}, "revision": 0}
        self.update_signal = "charge_tally_update_" + entry.entry_id
        self.config_signal = "charge_tally_config_" + entry.entry_id
        self.path = hass.config.path("charge_tally", "ledger.sqlite3")
        self._revision = 0
        self._period_unsub = None
        self._registry_unsub = None
        self._stop_unsub = None

    async def _worker(self, function, *args):
        return await self.hass.loop.run_in_executor(self.executor, partial(function, *args))

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
                result, snapshot = await self._worker(self._store.apply, method, *args)
                self._publish(snapshot)
                return result

    def _publish(self, snapshot):
        self._revision += 1
        self._decorate(snapshot)
        self.snapshot = snapshot
        async_dispatcher_send(self.hass, self.update_signal)
        self._schedule_timers()

    def _decorate(self, snapshot):
        snapshot["revision"] = self._revision
        for point in snapshot["points"]:
            point["utility_entities"] = self._helper_results.get(point["id"], {}).get("utility_entities", {})
            point["error"] = self._errors.get(point["id"])
            point["entity_id"] = er.async_get(self.hass).async_get_entity_id("sensor", "charge_tally", self.entry.entry_id + ":" + point["id"] + ":energy")
            if point["error"]:
                point["quality"] = sorted(set(point["quality"]) | {"helper_error"})
                point["available"] = False

    async def async_start(self):
        self._store = await self._worker(RuntimeStore, self.path, self.entry.data["currency"], self.hass.config.time_zone)
        await self.async_refresh_config(finish_helpers=False)
        @callback
        def minute(now):
            self._queue(self._apply("maintenance", now))
        self._period_unsub = async_track_utc_time_change(self.hass, minute, second=0)
        @callback
        def registry_changed(event):
            owned = {entity for result in self._helper_results.values() for entity in [result.get("integral_entity_id"), *result.get("utility_entities", {}).values()]}
            owned.update(point.get("entity_id") for point in self.snapshot["points"])
            if event.data.get("entity_id") in owned:
                self._queue(self.async_refresh_config())
        self._registry_unsub = self.hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, registry_changed)
        async def stopping(event):
            await self.async_close()
        self._stop_unsub = self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stopping)

    def _config(self):
        points, identities = {}, {}
        for subentry in self.entry.subentries.values():
            target = points if subentry.subentry_type == "point" else identities
            target[subentry.subentry_id] = deepcopy(dict(subentry.data))
        return points, identities

    async def async_refresh_config(self, *, finish_helpers=True):
        async with self._config_lock:
            if not self._closing:
                await self._refresh_config(finish_helpers=finish_helpers)

    async def _refresh_config(self, *, finish_helpers=True):
        points, identities = self._config()
        old_points = self.points
        old_sources = self._sources()
        removed = set(self.points) - set(points)
        await self._apply("configure", points, identities, dt_util.utcnow(), self.hass.config.time_zone)
        self.points = points
        for point_id in removed:
            from homeassistant.helpers import issue_registry as ir
            ir.async_delete_issue(self.hass, "charge_tally", self.entry.entry_id + ":" + point_id)
            try:
                await self._helpers.async_remove(point_id)
            except (ValueError, OSError, HelperSetupError) as err:
                _LOGGER.warning("Could not remove owned helpers for %s: %s", point_id, err)
            self._helper_results.pop(point_id, None)
            self._errors.pop(point_id, None)
        for point_id, point in points.items():
            try:
                self._helper_results[point_id] = await self._helpers.async_ensure(point_id, point)
                self._errors.pop(point_id, None)
            except (ValueError, OSError, HelperSetupError) as err:
                self._errors[point_id] = str(err)
        await self._bind_sources()
        self._subscribe()
        async_dispatcher_send(self.hass, self.config_signal)
        if finish_helpers:
            await self.async_finish_helpers()
        targets = {(point_id, role) for entity, pairs in self._sources().items() for point_id, role in pairs
                   if (point_id, role) not in old_sources.get(entity, [])
                   or (role == "price" and old_points.get(point_id, {}).get("price") != points[point_id]["price"])
                   or (role == "power" and old_points.get(point_id, {}).get("detection") != points[point_id].get("detection"))}
        await self._initial_observations(targets)

    async def async_finish_helpers(self):
        registry = er.async_get(self.hass)
        for point_id, point in self.points.items():
            entity_id = registry.async_get_entity_id("sensor", "charge_tally", self.entry.entry_id + ":" + point_id + ":energy")
            if entity_id:
                try:
                    self._helper_results[point_id] = await self._helpers.async_ensure(point_id, point, entity_id)
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
                ir.async_create_issue(self.hass, "charge_tally", issue_id, is_fixable=True,
                    severity=ir.IssueSeverity.WARNING, translation_key="helper_repair",
                    translation_placeholders={"name": self.points[point_id]["name"], "error": self._errors[point_id]},
                    data={"entry_id": self.entry.entry_id, "point_id": point_id})
            else:
                ir.async_delete_issue(self.hass, "charge_tally", issue_id)

    def _sources(self):
        result = {}
        for point_id, point in self.points.items():
            energy = self._helper_results.get(point_id, {}).get("integral_entity_id") if point["input_mode"] == "power" else point.get("energy_entity")
            for role, entity_id in (("energy", energy), ("power", point.get("power_entity") if point["input_mode"] != "energy" else None),
                                    ("price", point["price"].get("entity_id") if point["price"]["mode"] == "dynamic" else None)):
                if entity_id:
                    result.setdefault(entity_id, []).append((point_id, role))
        return result

    @staticmethod
    def _observation(state, at, entity_id=None):
        return {"entity_id": entity_id or (state.entity_id if state else None), "at": at.isoformat(), "value": state.state if state else None,
                "unit": state.attributes.get("unit_of_measurement") if state else None,
                "state_class": state.attributes.get("state_class") if state else None}

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
            observation = self._observation(event.data.get("new_state"), at, event.data["entity_id"])
            for point_id, role in sources.get(event.data["entity_id"], []):
                self._queue(self._handle_observation(point_id, role, observation))

        self._unsubs.extend((async_track_state_change_event(self.hass, list(sources), changed),
                             async_track_state_report_event(self.hass, list(sources), changed)))

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
            await self.async_recover_history(point_id, instant(gap["start"]), instant(gap["end"]))

    async def _initial_observations(self, targets):
        # Prices precede energy so the first measured interval has a valid anchor.
        items = [(point, role, self._observation(self.hass.states.get(entity), dt_util.utcnow(), entity))
                 for entity, pairs in self._sources().items() for point, role in pairs if (point, role) in targets]
        for point_id, role, data in sorted(items, key=lambda item: {"price": 0, "energy": 1, "power": 2}[item[1]]):
            await self._handle_observation(point_id, role, data)

    def _schedule_timers(self):
        if self._closed or self._closing:
            return
        desired = {}
        for point in self.snapshot["points"]:
            if not point.get("candidate"):
                continue
            config = self.points.get(point["id"], {}).get("detection", {})
            duration = config.get("start_seconds" if point["status"] == "pending_start" else "end_seconds")
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
                entity = self.points.get(point_id, {}).get("power_entity")
                observation = self._observation(self.hass.states.get(entity), now, entity)
                self._queue(self._handle_observation(point_id, "power", observation))

            self._timers[point_id] = async_track_point_in_utc_time(self.hass, timer, deadline)
            self._timer_deadlines[point_id] = deadline

    async def async_config_guard(self, point_id, old_data, new_data):
        return await self._apply("guard", point_id)

    async def async_snapshot(self, point_ids=None):
        result = deepcopy(self.snapshot) if point_ids is None else await self._read(self._store.snapshot, point_ids)
        self._decorate(result)
        registry = er.async_get(self.hass)
        for point in result["points"]:
            entity_id = registry.async_get_entity_id("select", "charge_tally", self.entry.entry_id + ":" + point["id"] + ":identity")
            anchor = registry.async_get(entity_id) if entity_id else None
            point["identity_entity_id"] = entity_id if anchor and anchor.config_entry_id == self.entry.entry_id and anchor.config_subentry_id == point["id"] and not anchor.disabled else None
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
        return await self._read(self._store.ledger.get_checkpoint, "api_" + kind + ":" + key)

    async def async_bind_preview(self, token, principal, point_id, expected_revision):
        return await self._apply("bind_preview", token, principal, point_id, expected_revision)

    async def async_public_command(self, command, payload, principal, authorize):
        return await self._apply("public_command", command, payload, principal, dt_util.utcnow(), authorize=authorize)

    async def async_command(self, command, payload):
        if command == "preview" and "energy_kwh" not in payload:
            data = dict(payload)
            if data.get("record_id"):
                detail = await self._apply("command", "record", {"record_id": data["record_id"]}, dt_util.utcnow())
                existing = detail["record"]
                if not any(k in data for k in ("start", "end", "point_id")):
                    return await self._apply("command", command, payload, dt_util.utcnow())
                data = {**existing, **data}
            await self.async_recover_history(data["point_id"], instant(data["start"]), instant(data["end"]))
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
            data["detection"] = {**data.get("detection", {}), "enabled": bool(payload["enabled"])}
            self.hass.config_entries.async_update_subentry(self.entry, subentry, data=data)
            await self.async_refresh_config()
        return result

    async def async_recover_history(self, point_id, start, end):
        point = self.points.get(point_id)
        if point is None:
            return
        missing = await self._apply("history_needed", point_id, start, end)
        if not missing:
            return
        entity_id = self._helper_results.get(point_id, {}).get("integral_entity_id") if point["input_mode"] == "power" else point.get("energy_entity")
        if not entity_id:
            return
        intervals = await self.history.async_intervals(entity_id, start, end, point.get("resetting", True), point.get("max_gap_seconds", 600))
        historical_prices = None
        if intervals and point["price"]["mode"] == "dynamic":
            historical_prices = await self.history.async_prices(point["price"]["entity_id"],
                min(instant(i["start"]) for i in intervals), max(instant(i["end"]) for i in intervals),
                self.entry.data["currency"], point["price"]["unit"])
        await self._apply("import_history", point_id, intervals, historical_prices)

    async def async_pre_backup(self):
        async with self._lock:
            if self._closed:
                return
            self._gate.clear()
            try:
                await self._worker(self._store.ledger.backup, self.hass.config.path("charge_tally", "ledger.backup.sqlite3"))
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
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._period_unsub:
            self._period_unsub()
            self._period_unsub = None
        if self._registry_unsub:
            self._registry_unsub()
            self._registry_unsub = None
        if self._stop_unsub:
            self._stop_unsub()
            self._stop_unsub = None
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()
        self._gate.set()
        if self._tasks:
            await asyncio.gather(*self._tasks)
        async with self._lock:
            self._closed = True
            if self._store:
                await self._worker(self._store.ledger.close)
        self.executor.shutdown(wait=False)
