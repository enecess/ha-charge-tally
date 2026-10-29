"""Serial-thread runtime state and transactional accounting adaptation."""

from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from . import reports
from .accounting import Accounting, allocatable, instant
from .archive import archive_ids
from .config_validation import BUILTIN_IDENTITY_NAME, validate_identity_name
from .const import UNAVAILABLE_TIMEOUT_SECONDS
from .core.detection import Detector
from .core.tariffs import DailySchedule
from .core.units import energy_kwh, power_w, price_per_kwh
from .ledger import Ledger
from .queries import summarize
from .record_views import detail_view, record_view


def required_roles(point, source):
    """Only measurement and active automatic detection can expire a record."""
    return (
        ("energy", "power")
        if point["input_mode"] == "power"
        or (point["input_mode"] == "energy_power" and source == "automatic")
        else ("energy",)
    )


class ScopedLedger:
    """Restrict records before passing the ledger to the shared query service."""

    def __init__(self, ledger, point_ids):
        self.ledger, self.point_ids = ledger, set(point_ids)

    def transaction(self):
        return self.ledger.transaction()

    def list_records(self, point_id=None, identity_id=None):
        return [
            r
            for r in self.ledger.list_records(point_id, identity_id)
            if r["point_id"] in self.point_ids
        ]

    def list_segments(self, record_id):
        return self.ledger.list_segments(record_id)

    def get_point(self, point_id):
        if point_id not in self.point_ids:
            return None
        return self.ledger.get_point(point_id)

    def get_identity(self, identity_id):
        if not self.point_ids:
            return None
        return self.ledger.get_identity(identity_id)

    def data_version(self):
        return self.ledger.data_version()


class RuntimeStore:
    """All methods, including construction and close, run on one worker."""

    def __init__(self, path, currency, timezone):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(path)
        try:
            self.ledger.bind_currency(currency)
        except BaseException:
            self.ledger.close()
            raise
        self.accounting = Accounting(
            self.ledger, self.preview_prices, self.preview_price_basis
        )
        self.currency, self.timezone = currency, timezone
        self._summary_version = None
        self._summary_cache = OrderedDict()
        self.states = self.ledger.get_checkpoint("runtime") or {}
        self.points = {}
        for state in self.states.values():
            state["available"] = False
            state["power_w"] = None
            state["interrupted"] = True
            state["detection_power_at"] = None
            if state.get("detector"):
                data = state["detector"]
                if data["state"] == "pending_start":
                    data.update(state="idle", candidate=None, identity_id=None)
                elif data["state"] == "pending_end":
                    data.update(state="charging", candidate=None)

    def change_currency(self, currency, expected_currency):
        """Update the cached currency only after the ledger accepts the change."""
        self.ledger.change_currency(currency, expected_currency)
        self.currency = currency

    def archive_catalog(self, points, identities):
        from .archive import ArchiveManager

        catalog = ArchiveManager(self.ledger).catalog(points, identities)
        catalog["targets"] = [
            item
            for item in catalog["targets"]
            if item["id"] == "unassigned" or identities[item["id"]].get("enabled", True)
        ]
        return catalog

    def _archive_guard(self, kind, object_id, points):
        ids = set(archive_ids(object_id))
        for point_id, state in self.states.items():
            detector = state.get("detector") or {}
            if (
                kind == "identity"
                and point_id in points
                and detector.get("candidate")
                and detector.get("identity_id") in ids
            ):
                raise ValueError("archive_busy")

    def archive_preview(
        self, kind, object_id, points, identities, target_identity_id=None
    ):
        from .archive import ArchiveManager

        self._archive_guard(kind, object_id, points)
        return ArchiveManager(self.ledger).preview(
            kind, object_id, points, identities, target_identity_id
        )

    def archive_prepare(
        self, kind, object_id, fingerprint, points, identities, target_identity_id=None
    ):
        """Keep deletion uncommitted until HA revalidates live configuration."""
        from .archive import ArchiveManager

        self._archive_guard(kind, object_id, points)
        ids = set(archive_ids(object_id))
        previous = deepcopy(self.states)
        transaction = self.ledger.transaction()
        transaction.__enter__()
        self._archive_transaction = (transaction, previous)
        try:
            result = ArchiveManager(self.ledger).delete(
                kind, object_id, fingerprint, points, identities, target_identity_id
            )
            if kind == "point":
                for id_ in ids:
                    self.states.pop(id_, None)
            else:
                for point_id, state in self.states.items():
                    if state.get("selected_identity_id") in ids:
                        state["selected_identity_id"] = (
                            target_identity_id or "unassigned"
                        )
                    if (
                        point_id not in points
                        and (state.get("detector") or {}).get("identity_id") in ids
                    ):
                        state["detector"] = None
            self.ledger.put_checkpoint("runtime", self.states)
            return result, self.snapshot()
        except BaseException:
            self.archive_finish(False)
            raise

    def archive_finish(self, commit):
        pending = getattr(self, "_archive_transaction", None)
        if pending is None:
            return
        transaction, previous = pending
        self._archive_transaction = None
        committed = False
        try:
            if commit:
                transaction.__exit__(None, None, None)
                committed = True
            else:
                error = RuntimeError("Archive transaction cancelled")
                transaction.__exit__(type(error), error, None)
        finally:
            if not committed:
                self._summary_cache.clear()
                if self.ledger._db.in_transaction:
                    self.ledger._db.rollback()
                self.states = previous

    def apply(self, method, *args):
        previous = deepcopy(self.states)
        points = deepcopy(self.points)
        timezone = self.timezone
        try:
            with self.ledger.transaction():
                result = getattr(self, method)(*args)
                self.ledger.put_checkpoint("runtime", self.states)
                snapshot = self.snapshot()
            return result, snapshot
        except BaseException:
            self._summary_cache.clear()
            self.states, self.points = previous, points
            self.timezone = timezone
            raise

    def configure(self, points, identities, at, timezone):
        identities = {
            id_: {**data, "name": validate_identity_name(data["name"])}
            for id_, data in identities.items()
            if id_ != "unassigned"
        }
        self.timezone = timezone
        identities = {
            **identities,
            "unassigned": {"name": BUILTIN_IDENTITY_NAME, "enabled": True},
        }
        for old in self.ledger.list_identities():
            if old["id"] not in identities:
                self.ledger.put_identity({**old, "active": False})
        for id_, data in identities.items():
            snapshot = {
                "id": id_,
                "name": data["name"],
                "active": data.get("enabled", True),
            }
            if snapshot != self.ledger.get_identity(id_):
                self.ledger.put_identity(snapshot)
        for old in self.ledger.list_points():
            if old["id"] not in points:
                self.ledger.put_point({**old, "active": False})
        for id_, data in points.items():
            snapshot = {
                **deepcopy(data),
                "id": id_,
                "active": True,
                "max_interval_seconds": data.get("max_gap_seconds", 600),
            }
            old = self.ledger.get_point(id_)
            if old != snapshot:
                self.ledger.put_point(snapshot)
            state = self.states.setdefault(
                id_,
                {
                    "selected_identity_id": "unassigned",
                    "normalized_energy_kwh": "0",
                    "reading": None,
                    "reading_at": None,
                    "available": False,
                    "power_w": None,
                    "power_at": None,
                    "current_price": None,
                    "quality": [],
                    "detector": None,
                },
            )
            selected = identities.get(state["selected_identity_id"])
            if not selected or not selected.get("enabled", True):
                state["selected_identity_id"] = "unassigned"
            if old and any(
                old.get(k) != snapshot.get(k)
                for k in ("input_mode", "energy_entity", "power_entity", "resetting")
            ):
                state.update(
                    reading=None,
                    reading_at=None,
                    available=False,
                    detector=None,
                    detection_power_at=None,
                    input_epoch=at.isoformat(),
                    outage=None,
                    resume_sources=None,
                    power_interrupted=False,
                )
            if old and old.get("detection") != data.get("detection"):
                state["detector"] = None
                state["detection_power_at"] = None
            if old is None or old.get("price") != data["price"]:
                price = data["price"]
                if old and any(
                    old["price"].get(key) != price.get(key)
                    for key in ("mode", "entity_id", "unit")
                ):
                    state["price_epoch"] = at.isoformat()
                self.put_price(
                    {
                        "point_id": id_,
                        "at": at.isoformat(),
                        **deepcopy(price),
                        "timezone": timezone,
                        **(
                            {"price": price["value"]}
                            if price["mode"] == "static"
                            else {"price": None}
                            if price["mode"] == "dynamic"
                            else {}
                        ),
                    }
                )
            state["current_price"] = self.prices(
                id_, at, at + timedelta(microseconds=1)
            )[-1][1]
            if state["current_price"] is not None:
                state["current_price"] = str(state["current_price"])
        self.points = deepcopy(points)
        for point_id in points:
            self.expire_unavailable(point_id, at)

    def put_price(self, data):
        sequence = (self.ledger.get_checkpoint("price_sequence") or 0) + 1
        self.ledger.put_checkpoint("price_sequence", sequence)
        self.ledger.put_price_version({"id": f"runtime-price:{sequence:020d}", **data})

    def prices(self, point_id, start, end):
        versions = self.ledger.list_price_versions(point_id)
        result = {start: None}
        for index, version in enumerate(versions):
            left = max(start, instant(version["at"]))
            right = (
                min(end, instant(versions[index + 1]["at"]))
                if index + 1 < len(versions)
                else end
            )
            if left >= right:
                continue
            if version.get("mode") == "tou":
                schedule = DailySchedule(version["schedule"])
                zone = version.get("timezone", self.timezone)
                for at in [left, *schedule.boundaries(left, right, zone)]:
                    result[at] = schedule.price_at(at, zone)
            else:
                value = version.get("price")
                result[left] = None if value is None else Decimal(value)
        # Stored interval prices are immutable evidence for their covered range.
        for observation in self.ledger.list_intervals(
            point_id, start.isoformat(), end.isoformat()
        ):
            if not allocatable(observation):
                continue
            left, right = (
                max(start, instant(observation["start"])),
                min(end, instant(observation["end"])),
            )
            active = None
            for at, price in observation["prices"]:
                at = instant(at)
                value = None if price is None else Decimal(price)
                if at <= left:
                    active = value
                elif at < right:
                    result[at] = value
            result[left] = active
            if right < end and not any(instant(v["at"]) <= right for v in versions):
                result[right] = None
        for gap in self.ledger.get_checkpoint("_price_gaps:" + point_id) or []:
            if instant(gap["start"]) < end and instant(gap["end"]) > start:
                result[max(start, instant(gap["start"]))] = None
                for at in list(result):
                    if instant(gap["start"]) <= at < instant(gap["end"]):
                        result[at] = None
        return sorted(result.items())

    def preview_prices(self, point_id, start, end):
        return [
            (at.isoformat(), None if price is None else str(price))
            for at, price in self.prices(point_id, start, end)
        ]

    def preview_price_basis(self, point_id, start, end):
        versions = self.ledger.list_price_versions(point_id)
        relevant = [
            version
            for index, version in enumerate(versions)
            if instant(version["at"]) < end
            and (
                index + 1 == len(versions) or instant(versions[index + 1]["at"]) > start
            )
        ]
        return {
            "timeline": self.preview_prices(point_id, start, end),
            "versions": relevant,
        }

    def active(self, point_id):
        return next(
            (
                r
                for r in self.ledger.list_records(point_id=point_id)
                if r["status"] == "active"
            ),
            None,
        )

    def guard(self, point_id):
        state = self.states.get(point_id, {})
        return not self.active(point_id) and not (state.get("detector") or {}).get(
            "candidate"
        )

    def _update_unavailable(self, point_id, at):
        state = self.states[point_id]
        record = self.active(point_id)
        if record is None:
            state.pop("outage", None)
            return
        roles = required_roles(self.points[point_id], record["source"])
        if state.get("available") and (
            "power" not in roles or state.get("power_w") is not None
        ):
            state.pop("outage", None)
        elif not state.get("outage") or state["outage"]["record_id"] != record["id"]:
            state["outage"] = {"record_id": record["id"], "since": at.isoformat()}

    def expire_unavailable(self, point_id, at):
        state = self.states.get(point_id)
        if state is None or not (outage := state.get("outage")):
            return
        record = self.active(point_id)
        if record is None or record["id"] != outage["record_id"]:
            state.pop("outage", None)
            return
        since = instant(outage["since"])
        if at < since + timedelta(seconds=UNAVAILABLE_TIMEOUT_SECONDS):
            return
        self.accounting.end(
            record["id"],
            since,
            "source_unavailable:" + record["id"] + ":" + outage["since"],
            reason="source_unavailable",
        )
        state.pop("outage", None)
        state["resume_sources"] = list(
            required_roles(self.points[point_id], record["source"])
        )
        state["detection_power_at"] = None
        state["detector"] = {
            "state": "idle",
            "candidate": None,
            "identity_id": None,
            "last_at": at.isoformat(),
            "blocked": False,
        }

    def observe(self, point_id, role, observation):
        if point_id not in self.points:
            return
        point, state = self.points[point_id], self.states[point_id]
        expected = (
            (
                point.get("energy_entity")
                if point["input_mode"] != "power"
                else state.get("bindings", {}).get("energy")
            )
            if role == "energy"
            else point.get("power_entity")
            if role == "power"
            else point["price"].get("entity_id")
        )
        if observation.get("entity_id") and observation["entity_id"] != expected:
            return
        at = instant(observation["at"])
        if (
            state.get("input_epoch")
            and role != "price"
            and at < instant(state["input_epoch"])
        ):
            return
        key = role + "_event_at"
        if state.get(key) and at < instant(state[key]):
            return
        if state.get(role + "_event") == observation and not (
            role == "energy" and not state.get("available")
        ):
            return
        state[key] = at.isoformat()
        state[role + "_event"] = observation
        try:
            raw, unit = observation["value"], observation.get("unit")
            if role == "energy":
                if observation.get("state_class") not in ("total", "total_increasing"):
                    raise ValueError("Cumulative energy required")
                value = energy_kwh(raw, unit)
            elif role == "power":
                value = power_w(raw, unit)
            else:
                value = price_per_kwh(
                    raw, unit or point["price"].get("unit"), self.currency
                )
        except (ValueError, TypeError):
            value = None
        if role == "price":
            state["current_price"] = None if value is None else str(value)
            self.put_price(
                {
                    "point_id": point_id,
                    "at": at.isoformat(),
                    "mode": "dynamic",
                    "price": state["current_price"],
                }
            )
        elif role == "power":
            self.expire_unavailable(point_id, at)
            state["power_w"] = None if value is None else str(value)
            state["power_at"] = at.isoformat()
            if value is None and point["input_mode"] == "power":
                state["power_interrupted"] = True
            self._update_unavailable(point_id, at)
            self.detect(
                point_id,
                at,
                value,
                evidence=observation.get("detection_evidence", True),
            )
        else:
            return self.energy(point_id, at, value)

    def energy(self, point_id, at, value):
        point, state = self.points[point_id], self.states[point_id]
        self.expire_unavailable(point_id, at)
        recovering = not state.get("available") or bool(state.get("resume_sources"))
        if value is None:
            state.update(available=False, interrupted=True, quality=["unavailable"])
            self._update_unavailable(point_id, at)
            self.detect(point_id, at, None)
            return
        previous = state.get("reading")
        recovery = None
        if previous is not None and at <= instant(state["reading_at"]):
            if at == instant(state["reading_at"]) and value == Decimal(previous):
                state["available"] = True
                self._update_unavailable(point_id, at)
            return
        if previous is not None and at > instant(state["reading_at"]):
            delta = value - Decimal(previous)
            quality = []
            if delta < 0:
                quality = ["reset"]
                if not point.get("resetting", True):
                    state.update(
                        reading=str(value),
                        reading_at=at.isoformat(),
                        available=False,
                        interrupted=True,
                        quality=["unexpected_reset"],
                    )
                    self.detect(point_id, at, None)
                    self._update_unavailable(point_id, at)
                    return
                delta = value
            if state.get("interrupted") or state.get("power_interrupted"):
                quality.append("unavailable")
            left = instant(state["reading_at"])
            if (at - left).total_seconds() > point.get("max_gap_seconds", 600):
                quality.append("gap")
            state["normalized_energy_kwh"] = str(
                Decimal(state["normalized_energy_kwh"]) + delta
            )
            self.accounting.add_interval(
                point_id, left, at, delta, self.prices(point_id, left, at), quality
            )
            state["quality"] = quality
            if quality:
                recovery = {"start": left.isoformat(), "end": at.isoformat()}
        state.update(
            reading=str(value),
            reading_at=at.isoformat(),
            available=True,
            interrupted=False,
        )
        if state.get("power_w") is not None:
            state["power_interrupted"] = False
        if state.get("resume_sources") and (
            "power" not in state["resume_sources"] or state.get("power_w") is not None
        ):
            state.pop("resume_sources")
        self._update_unavailable(point_id, at)
        if recovering:
            self.detect(
                point_id,
                at,
                None if state.get("power_w") is None else Decimal(state["power_w"]),
                evidence=False,
            )
        return recovery

    def bind_sources(self, sources, errors, now):
        for point_id in self.points:
            state = self.states[point_id]
            state["bindings"] = sources.get(point_id, {})
            state["helper_error"] = errors.get(point_id)
            if state["helper_error"]:
                self.detect(point_id, now, None)

    def detect(self, point_id, at, power, *, evidence=True):
        point, state = self.points[point_id], self.states[point_id]
        config = point.get("detection", {})
        if not config.get("enabled"):
            return
        last = (state.get("detector") or {}).get("last_at")
        if last and at < instant(last):
            return
        # Timer and initial snapshots may advance detection, but are not fresh reports.
        if power is None or not state.get("available") or state.get("helper_error"):
            state["detection_power_at"] = None
        elif evidence:
            state["detection_power_at"] = at.isoformat()
            state["detection_power_w"] = str(power)
        active = self.active(point_id)
        if active and active["source"] == "manual":
            return
        detector = Detector(
            config["start_w"],
            config["end_w"],
            config["start_seconds"],
            config["end_seconds"],
        )
        if state.get("detector"):
            detector.restore(state["detector"], interrupted=False)
        events = detector.observe(
            at,
            power
            if state.get("available")
            and not state.get("helper_error")
            and not state.get("resume_sources")
            and (evidence or not detector.snapshot().get("blocked"))
            else None,
            state["selected_identity_id"],
        )
        for event in events:
            if event["kind"] == "start" and not active:
                identity = self.ledger.get_identity(event["identity_id"])
                if identity and identity.get("active", True):
                    self.accounting.start(
                        point_id,
                        event["identity_id"],
                        instant(event["at"]),
                        uuid4().hex,
                        source="automatic",
                        timezone=self.timezone,
                    )
                else:
                    detector.force_stop()
            elif event["kind"] == "end" and active:
                self.accounting.end(active["id"], instant(event["at"]), uuid4().hex)
        state["detector"] = detector.snapshot()

    def command(self, command, payload, now, source_available=True):
        if command not in ("start", "end", "commit_preview"):
            return self._command(command, payload, now)
        key = "runtime_request:" + payload["request_id"]
        previous = self.ledger.get_checkpoint(key)
        if previous:
            if previous["command"] != command or previous["payload"] != payload:
                raise ValueError("Request ID reused with different content")
            return previous["result"]
        result = self._command(command, payload, now, source_available)
        self.ledger.put_checkpoint(
            key, {"command": command, "payload": payload, "result": result}
        )
        return result

    def bind_preview(self, token, principal, point_id, expected_revision):
        self.ledger.put_checkpoint(
            "api_preview:" + token,
            {
                "principal": principal,
                "point_id": point_id,
                "expected_revision": expected_revision,
            },
        )

    def public_command(self, command, payload, principal, now, source_available=True):
        from hashlib import sha256

        key = sha256((principal + ":" + payload["request_id"]).encode()).hexdigest()
        previous = self.ledger.get_checkpoint("api_request:" + key)
        if previous:
            if previous["command"] != command or previous["payload"] != payload:
                raise ValueError("Request ID reused with different content")
            return previous["result"]
        data = dict(payload)
        if command == "start" and self.states[data["point_id"]].get("helper_error"):
            raise ValueError("Repair the point helpers before starting")
        if command in ("end", "reassign", "void"):
            self.accounting._record(data["record_id"], data["expected_revision"])
            data.pop("point_id", None)
        if command == "end":
            data.pop("expected_revision")
        if command in ("reassign", "void"):
            data.pop("request_id")
        else:
            data["request_id"] = "api:" + key
        if command == "commit":
            data.pop("expected_revision", None)
        result = self.command(
            "commit_preview" if command == "commit" else command,
            data,
            now,
            source_available,
        )
        self.ledger.put_checkpoint(
            "api_request:" + key,
            {"command": command, "payload": payload, "result": result},
        )
        return result

    def _command(self, command, payload, now, source_available=True):
        data = dict(payload)
        if command == "start":
            point_id = data["point_id"]
            state = self.states[point_id]
            request_id = data["request_id"]
            if (
                not source_available
                or not state.get("available")
                or state.get("resume_sources")
            ) and self.ledger.get_request(request_id) is None:
                raise ValueError(
                    "A valid measurement baseline is required; use historical entry"
                )
            # Persist the original instant for retries that omit it.
            key = "command_time:" + request_id
            at = (
                instant(data["at"])
                if data.get("at")
                else instant(self.ledger.get_checkpoint(key) or now.isoformat())
            )
            self.ledger.put_checkpoint(key, at.isoformat())
            result = self.accounting.start(
                point_id,
                data.get("identity_id", state["selected_identity_id"]),
                at,
                request_id,
                timezone=self.timezone,
            )
            if self.points[point_id].get("detection", {}).get("enabled"):
                detector = state.get("detector") or {}
                state["detector"] = {
                    **detector,
                    "state": "idle",
                    "candidate": None,
                    "identity_id": None,
                    "last_at": max(now.isoformat(), detector.get("last_at") or ""),
                }
            self._update_unavailable(point_id, now)
            return result
        if command == "end":
            record = self.ledger.get_record(data["record_id"])
            if not record:
                raise ValueError("Unknown record")
            key = "command_time:" + data["request_id"]
            at = (
                instant(data["at"])
                if data.get("at")
                else instant(self.ledger.get_checkpoint(key) or now.isoformat())
            )
            self.ledger.put_checkpoint(key, at.isoformat())
            result = self.accounting.end(record["id"], at, data["request_id"])
            state = self.states[record["point_id"]]
            state.pop("outage", None)
            config = self.points.get(record["point_id"], {}).get("detection", {})
            if config.get("enabled"):
                observed = state.get("detection_power_at")
                recent_low = (
                    source_available
                    and state.get("available")
                    and not state.get("helper_error")
                    and observed is not None
                    and 0
                    <= (now - instant(observed)).total_seconds()
                    <= self.points[record["point_id"]].get("max_gap_seconds", 600)
                    and Decimal(state["detection_power_w"])
                    < Decimal(str(config["end_w"]))
                )
                state["detector"] = {
                    "state": "idle",
                    "candidate": None,
                    "identity_id": None,
                    "last_at": max(
                        now.isoformat(),
                        (state.get("detector") or {}).get("last_at") or "",
                    ),
                    "blocked": not recent_low,
                }
            return result
        if command == "select_identity":
            identity = self.ledger.get_identity(data["identity_id"])
            if not identity or not identity.get("active", True):
                raise ValueError("An active identity is required")
            state = self.states[data["point_id"]]
            state["selected_identity_id"] = data["identity_id"]
            detector = state.get("detector")
            if detector and detector["state"] == "pending_start":
                detector["identity_id"] = data["identity_id"]
            return {"point_id": data["point_id"], "identity_id": data["identity_id"]}
        if command == "set_detection":
            point = self.points[data["point_id"]]
            if not self.guard(data["point_id"]):
                raise ValueError("Point has an active record or detection candidate")
            config = point.get("detection", {})
            if data["enabled"]:
                if point["input_mode"] == "energy" or not all(
                    k in config
                    for k in ("start_w", "end_w", "start_seconds", "end_seconds")
                ):
                    raise ValueError("Configure power detection thresholds first")
                Detector(
                    config["start_w"],
                    config["end_w"],
                    config["start_seconds"],
                    config["end_seconds"],
                )
            return {"point_id": data["point_id"], "enabled": bool(data["enabled"])}
        if command in ("reassign", "void"):
            if command == "void":
                record = self.ledger.get_record(data["record_id"])
                if record and record["status"] == "active":
                    raise ValueError("End the active record before voiding it")
            return getattr(self.accounting, command)(**data)
        if command == "preview":
            existing = (
                self.ledger.get_record(data["record_id"])
                if data.get("record_id")
                else {}
            )
            if not existing:
                data.setdefault("timezone", self.timezone)
            return self.accounting.preview(data)
        if command == "commit_preview":
            return self.accounting.commit_preview(**data)
        if command == "record":
            record = self.ledger.get_record(data["record_id"])
            if not record:
                raise ValueError("Unknown record")
            return detail_view(
                record,
                self.ledger.list_segments(record["id"]),
                self.ledger.list_revisions(record["id"]),
            )
        if command == "summary":
            return summarize(
                self.ledger,
                instant(data["start"]) if data.get("start") else None,
                instant(data["end"]) if data.get("end") else None,
                identity_id=data.get("identity_id"),
                point_id=data.get("point_id"),
                calendar=self.calendar_label(data),
                bucket_period=data.get("bucket_period", "auto"),
                timezone=self.timezone,
            )
        raise ValueError("Unknown command")

    def _record_view(self, record):
        return record_view(
            record,
            None
            if "has_known_cost" in record
            else self.ledger.list_segments(record["id"]),
        )

    def snapshot(self, point_ids=None):
        scoped = (
            self.ledger if point_ids is None else ScopedLedger(self.ledger, point_ids)
        )
        # Summaries and reset markers must describe the same calendar instant.
        day = (
            datetime.now(UTC)
            .astimezone(ZoneInfo(self.timezone))
            .replace(hour=0, minute=0, second=0, microsecond=0, fold=0)
        )
        period_starts = {
            "daily": day,
            "monthly": day.replace(day=1),
            "yearly": day.replace(month=1, day=1),
        }
        allowed = (
            [point["id"] for point in self.ledger.list_points()]
            if point_ids is None
            else point_ids
        )
        points = []
        for point_id, point in self.points.items():
            if point_ids is not None and point_id not in point_ids:
                continue
            state = self.states[point_id]
            records = self.ledger.list_records(point_id=point_id)
            active = next(
                (record for record in records if record["status"] == "active"), None
            )
            last_record = max(
                (record for record in records if record["status"] == "ended"),
                key=lambda record: (record["end"], record["id"]),
                default=None,
            )
            detector = state.get("detector") or {}
            recording_state = active["source"] if active else "idle"
            detection_state = (
                "disabled"
                if not point.get("detection", {}).get("enabled")
                else "paused_manual"
                if recording_state == "manual"
                else "blocked"
                if detector.get("blocked")
                else "unavailable"
                if not state.get("available")
                or state.get("helper_error")
                or state.get("power_w") is None
                else detector.get("state", "charging" if active else "idle")
            )
            if detection_state == "idle":
                detection_state = "waiting"
            points.append(
                {
                    "id": point_id,
                    "name": point["name"],
                    "selected_identity_id": state["selected_identity_id"],
                    "active_record": self._record_view(active) if active else None,
                    "last_record": self._record_view(last_record)
                    if last_record
                    else None,
                    "unavailable_since": state["outage"]["since"]
                    if state.get("outage")
                    else None,
                    "unavailable_deadline": (
                        instant(state["outage"]["since"])
                        + timedelta(seconds=UNAVAILABLE_TIMEOUT_SECONDS)
                    ).isoformat()
                    if state.get("outage")
                    else None,
                    "recording_state": recording_state,
                    "detection_state": detection_state,
                    "candidate_identity_id": detector.get("identity_id")
                    if detection_state == "pending_start"
                    else None,
                    "normalized_energy_kwh": state["normalized_energy_kwh"],
                    "power_w": state.get("power_w"),
                    "current_price": state.get("current_price"),
                    "status": "charging"
                    if active and active["source"] == "manual"
                    else (state.get("detector") or {}).get(
                        "state", "charging" if active else "idle"
                    ),
                    "quality": state.get("quality", []),
                    "available": state.get("available", False)
                    and not state.get("resume_sources"),
                    "detection_enabled": point.get("detection", {}).get(
                        "enabled", False
                    ),
                    "candidate": (state.get("detector") or {}).get("candidate"),
                    "utility_entities": {},
                }
            )
        identities = self.ledger.list_identities()
        for identity in identities:
            identity["summaries"] = {
                period: self.scoped_summary(
                    allowed,
                    {"identity_id": identity["id"], "calendar_period": period},
                    now=day,
                )
                for period in ("total", "daily", "monthly", "yearly")
            }
        archived = [
            {**point, "identity_entity_id": None}
            for point in self.ledger.list_points()
            if not point.get("active", True)
            and (point_ids is None or point["id"] in point_ids)
        ]
        return {
            "currency": self.currency,
            "timezone": self.timezone,
            "identities": identities,
            "points": points,
            "archived_points": archived,
            "records": [self._record_view(record) for record in scoped.list_records()],
            "summary": self.scoped_summary(allowed, {}, now=day),
            "revision": self.ledger.data_version(),
            "period_starts": {
                period: start.isoformat() for period, start in period_starts.items()
            },
        }

    def calendar_label(self, data, *, now=None):
        if "calendar_period" not in data:
            return None
        if (
            "start" in data
            or "end" in data
            or data["calendar_period"] not in ("daily", "monthly", "yearly", "total")
        ):
            raise ValueError("Invalid calendar query")
        if data["calendar_period"] == "total":
            return None
        today = (
            (now if now is not None else datetime.now(UTC))
            .astimezone(ZoneInfo(self.timezone))
            .date()
            .isoformat()
        )
        return today[
            : {"daily": 10, "monthly": 7, "yearly": 4}[data["calendar_period"]]
        ]

    def scoped_summary(
        self,
        point_ids,
        data,
        *,
        include_records=False,
        now=None,
        max_records=None,
        max_segments=None,
    ):
        start = instant(data["start"]) if data.get("start") else None
        end = instant(data["end"]) if data.get("end") else None
        calendar = self.calendar_label(data, now=now)
        version = self.ledger.data_version()
        if self._summary_version != version:
            self._summary_cache.clear()
            self._summary_version = version
        key = (
            tuple(sorted(set(point_ids))),
            start,
            end,
            data.get("identity_id"),
            data.get("point_id"),
            calendar,
            data.get("bucket_period", "auto"),
            self.timezone,
        )
        if not include_records and key in self._summary_cache:
            self._summary_cache.move_to_end(key)
            return deepcopy(self._summary_cache[key])
        result = summarize(
            ScopedLedger(self.ledger, point_ids),
            start,
            end,
            identity_id=data.get("identity_id"),
            point_id=data.get("point_id"),
            calendar=calendar,
            bucket_period=data.get("bucket_period", "auto"),
            timezone=self.timezone,
            include_records=include_records,
            max_records=max_records,
            max_segments=max_segments,
        )
        if not include_records:
            self._summary_cache[key] = deepcopy(result)
            if len(self._summary_cache) > 128:
                self._summary_cache.popitem(last=False)
        return result

    def query(self, command, data, point_ids):
        if command == "report":
            with self.ledger.transaction():
                generated_at = datetime.now(UTC)
                allowed = (
                    [p["id"] for p in self.ledger.list_points()]
                    if point_ids is None
                    else point_ids
                )
                summary = self.scoped_summary(
                    allowed,
                    data,
                    include_records=True,
                    now=generated_at,
                    max_records=reports.MAX_REPORT_RECORDS,
                    max_segments=reports.MAX_REPORT_SEGMENTS,
                )
                scope = {
                    "calendar_period": data.get("calendar_period"),
                    "calendar": self.calendar_label(data, now=generated_at),
                    "start": instant(data["start"]).isoformat()
                    if data.get("start")
                    else None,
                    "end": instant(data["end"]).isoformat()
                    if data.get("end")
                    else None,
                    "point_id": data.get("point_id"),
                    "identity_id": data.get("identity_id"),
                }
                return reports.build_report(
                    ScopedLedger(self.ledger, allowed),
                    summary,
                    scope=scope,
                    currency=self.currency,
                    timezone=self.timezone,
                    generated_at=generated_at,
                )
        allowed = (
            [p["id"] for p in self.ledger.list_points()]
            if point_ids is None
            else point_ids
        )
        if command == "summary":
            return self.scoped_summary(allowed, data)
        if command == "record":
            record = self.ledger.get_record(data["record_id"])
            if not record or record["point_id"] not in allowed:
                raise ValueError("Unknown authorized record")
            return {
                **detail_view(
                    record,
                    self.ledger.list_segments(record["id"]),
                    self.ledger.list_revisions(record["id"]),
                ),
                "point": self.ledger.get_point(record["point_id"]),
                "identity": self.ledger.get_identity(record["identity_id"]),
            }
        if command != "records":
            raise ValueError("Unknown query")
        offset, limit = data.get("offset", 0), data.get("limit", 50)
        if (
            not isinstance(offset, int)
            or not isinstance(limit, int)
            or offset < 0
            or not 1 <= limit <= 500
        ):
            raise ValueError("Invalid query page")
        records, total = self.ledger.record_page(
            allowed,
            point_id=data.get("point_id"),
            identity_id=data.get("identity_id"),
            include_void=data.get("include_void", False),
            start=instant(data["start"]).isoformat() if data.get("start") else None,
            end=instant(data["end"]).isoformat() if data.get("end") else None,
            offset=offset,
            limit=limit,
        )
        return {
            "records": [self._record_view(record) for record in records],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    def history_needed(self, point_id, start, end):
        cursor = start
        for interval in self.ledger.list_intervals(
            point_id, start.isoformat(), end.isoformat()
        ):
            if interval["gap"] or instant(interval["start"]) > cursor:
                return True
            cursor = max(cursor, instant(interval["end"]))
        return cursor < end

    def import_history(self, point_id, intervals, historical_prices=None):
        with self.accounting.batch_refresh():
            epoch = self.states[point_id].get("input_epoch")
            valid = [
                i
                for i in intervals
                if not i.get("gap")
                and not i.get("quality")
                and (epoch is None or i["start"] >= epoch)
            ]
            existing = self.ledger.list_intervals(point_id)
            for gap in [i for i in existing if i["gap"]]:
                # Integral history cannot recover unsampled raw power.
                if (
                    self.points[point_id]["input_mode"] == "power"
                    and "unavailable" in gap["quality"]
                ):
                    continue
                parts = [
                    i
                    for i in valid
                    if i["start"] >= gap["start"] and i["end"] <= gap["end"]
                ]
                cursor = gap["start"]
                for part in parts:
                    if part["start"] != cursor:
                        break
                    cursor = part["end"]
                if cursor == gap["end"] and sum(
                    (Decimal(i["energy_kwh"]) for i in parts), Decimal(0)
                ) == Decimal(gap["energy_kwh"]):
                    replacements = [
                        {
                            **i,
                            "prices": self.history_prices(
                                point_id,
                                instant(i["start"]),
                                instant(i["end"]),
                                historical_prices,
                            ),
                        }
                        for i in parts
                    ]
                    self.accounting.replace_gap(
                        point_id,
                        instant(gap["start"]),
                        instant(gap["end"]),
                        replacements,
                    )
            existing = self.ledger.list_intervals(point_id)
            candidates = [
                interval
                for interval in intervals
                if (epoch is None or interval["start"] >= epoch)
                and (
                    interval in valid
                    or self.points[point_id]["input_mode"] in ("energy", "energy_power")
                    and not set(interval.get("quality", ()))
                    & {"reset", "missing_energy"}
                )
            ]
            for interval in candidates:
                if any(
                    old["start"] < interval["end"] and old["end"] > interval["start"]
                    for old in existing
                ):
                    continue
                left, right = instant(interval["start"]), instant(interval["end"])
                self.accounting.add_interval(
                    point_id,
                    left,
                    right,
                    Decimal(interval["energy_kwh"]),
                    self.history_prices(point_id, left, right, historical_prices),
                    interval.get("quality", ()),
                )
                existing.append(interval)

    def history_prices(self, point_id, start, end, historical_prices):
        own = dict(self.prices(point_id, start, end))
        if not historical_prices:
            return sorted(own.items())
        epoch = self.states[point_id].get("price_epoch")
        versions = self.ledger.list_price_versions(point_id)
        boundaries = sorted(
            set(own) | {at for at, _ in historical_prices if start < at < end}
        )
        result = []
        for at in boundaries:
            active = next(
                (v for v in reversed(versions) if instant(v["at"]) <= at), None
            )
            dynamic = (
                active.get("mode") == "dynamic"
                if active
                else self.points[point_id]["price"]["mode"] == "dynamic"
            )
            value = next(
                (value for time, value in reversed(sorted(own.items())) if time <= at),
                None,
            )
            if dynamic and (epoch is None or at >= instant(epoch)):
                value = next(
                    (
                        value
                        for time, value in reversed(historical_prices)
                        if time <= at
                    ),
                    None,
                )
            result.append((at, value))
        return result

    def maintenance(self, now):
        for point_id, state in self.states.items():
            if point_id in self.points:
                self.expire_unavailable(point_id, now)
                price = self.prices(point_id, now, now + timedelta(microseconds=1))[-1][
                    1
                ]
                state["current_price"] = None if price is None else str(price)
        date = now.date().isoformat()
        if self.ledger.get_checkpoint("pruned_on") != date:
            if self.ledger.prune(before=now - timedelta(days=90), limit=500) < 500:
                self.ledger.put_checkpoint("pruned_on", date)
