"""Record lifecycle and version-bound historical accounting previews."""

from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from hashlib import sha256
from uuid import uuid4
from zoneinfo import ZoneInfo

from .core.segments import split_interval
from .core.tariffs import elapsed, utc
from .core.units import decimal_value
from .ledger import encode


def instant(value):
    return utc(datetime.fromisoformat(value) if isinstance(value, str) else value)


def totals(record, segments, quality=(), *, append=False):
    marks = set(quality)
    for segment in segments:
        marks.update(segment["quality"])
        if segment["cost"] is None:
            marks.add("missing_price")
    marks.discard("price_unknown")
    if record["status"] == "active":
        marks.add("provisional")
    with localcontext() as ctx:
        ctx.prec = 36
        energy = Decimal(record["energy_kwh"]) if append else Decimal(0)
        cost = Decimal(record["known_cost"]) if append else Decimal(0)
        for segment in segments:
            energy += Decimal(segment["energy_kwh"])
            if segment["cost"] is not None:
                cost += Decimal(segment["cost"])
        record.update(
            energy_kwh=str(energy),
            known_cost=str(cost),
            cost_complete=not bool(
                marks & {"missing_price", "missing_energy", "pending_settlement"}
            ),
            quality=sorted(marks),
        )
    return record


class Accounting:
    def __init__(self, ledger, price_resolver=None, price_basis=None):
        self.ledger = ledger
        self.price_resolver = price_resolver or self._historical_prices
        self.price_basis = price_basis or self.price_resolver
        self._refresh_pending = None

    def _references(self, point_id, identity_id, original=None):
        point, identity = (
            self.ledger.get_point(point_id),
            self.ledger.get_identity(identity_id),
        )
        if point is None or identity is None:
            raise ValueError("Unknown point or identity")
        for key, snapshot in (("point_id", point), ("identity_id", identity)):
            retained = original is not None and original[key] == snapshot["id"]
            if not retained and snapshot.get("active", True) is False:
                raise ValueError("Point or identity is disabled")

    def _request(self, request_id, payload, operation):
        if not request_id:
            raise ValueError("A request ID is required")
        digest = sha256(encode(payload).encode()).hexdigest()
        with self.ledger.transaction():
            old = self.ledger.get_request(request_id)
            if old:
                if old["digest"] != digest:
                    raise ValueError("Request ID reused with different content")
                return old["result"]
            result = operation()
            self.ledger.put_request(request_id, {"digest": digest, "result": result})
            return result

    def _record(self, record_id, expected_revision=None):
        record = self.ledger.get_record(record_id)
        if record is None or record["status"] == "void":
            raise ValueError("Unknown or void record")
        if expected_revision is not None and record["revision"] != expected_revision:
            raise ValueError("Record revision conflict")
        return record

    def _build(self, record):
        start = instant(record["start"])
        end = instant(record["end"]) if record["end"] else None
        segments, coverage, quality = [], [], set()
        intervals = self.ledger.list_intervals(
            record["point_id"], record["start"], record["end"]
        )
        boundaries = [start] + ([end] if end else [])
        for other in self.ledger.list_records(point_id=record["point_id"]):
            boundaries.append(instant(other["start"]))
            if other["end"]:
                boundaries.append(instant(other["end"]))
        for observation in intervals:
            left, right = instant(observation["start"]), instant(observation["end"])
            if observation.get("gap"):
                quality.add("missing_energy")
                continue
            parts = self._observation_parts(record, observation, boundaries)
            for part in parts:
                if instant(part["start"]) >= start and (
                    end is None or instant(part["end"]) <= end
                ):
                    segments.append(part)
                    coverage.append({"start": part["start"], "end": part["end"]})
        coverage.sort(key=lambda s: s["start"])
        merged = []
        for item in coverage:
            if merged and merged[-1]["end"] >= item["start"]:
                merged[-1]["end"] = max(merged[-1]["end"], item["end"])
            else:
                merged.append(dict(item))
        latest = max((instant(i["end"]) for i in intervals), default=start)
        horizon = end or latest
        cursor, missing = start, []
        for item in merged:
            left, right = instant(item["start"]), instant(item["end"])
            if left > cursor:
                missing.append((cursor, left))
            cursor = max(cursor, right)
        if cursor < horizon:
            missing.append((cursor, horizon))
        record["quality_spans"] = []
        for left, right in missing:
            marks = {"missing_energy"}
            if end and right > latest:
                marks.add("pending_settlement")
            for observation in intervals:
                if (
                    observation.get("gap")
                    and instant(observation["start"]) < right
                    and instant(observation["end"]) > left
                ):
                    marks.update(observation["quality"])
            quality.update(marks)
            record["quality_spans"].append(
                dict(
                    start=left.isoformat(), end=right.isoformat(), quality=sorted(marks)
                )
            )
        if record.get("manual_fee_override"):
            segments = self._manual_fee(record, segments)
        record.update(
            _accounted_until=horizon.isoformat(), _segment_count=len(segments)
        )
        return totals(record, segments, quality), segments, merged

    def _observation_parts(self, record, observation, boundaries=()):
        parts = split_interval(
            instant(observation["start"]),
            instant(observation["end"]),
            Decimal(observation["energy_kwh"]),
            record["timezone"],
            [
                (instant(at), None if price is None else Decimal(price))
                for at, price in observation["prices"]
            ],
            boundaries,
        )
        for part in parts:
            part["observation_id"] = observation["id"]
            part["quality"] = sorted(
                set(part["quality"])
                | set(observation["quality"])
                | ({"estimated"} if len(parts) > 1 else set())
            )
        return parts

    def _append_observation(self, record: dict, observation: dict) -> bool:
        if (
            record["status"] != "active"
            or record.get("manual_override")
            or record.get("manual_fee_override")
            or record.get("quality_spans")
            or observation.get("gap")
            or record["point_id"] != observation["point_id"]
            or record.get("_accounted_until") != observation["start"]
            or instant(record["start"]) > instant(observation["start"])
            or instant(observation["end"]) <= instant(observation["start"])
        ):
            return False
        parts = self._observation_parts(record, observation)
        updated = totals(dict(record), parts, record["quality"], append=True)
        updated.update(
            _accounted_until=observation["end"],
            _segment_count=record["_segment_count"] + len(parts),
            revision=record["revision"] + 1,
        )
        self.ledger.append_record_segments(updated, parts, record["_segment_count"])
        return True

    def _manual_fee(self, record, segments):
        start, end = instant(record["start"]), instant(record["end"])
        for span in record.get("quality_spans", []):
            for part in split_interval(
                instant(span["start"]),
                instant(span["end"]),
                Decimal(0),
                record["timezone"],
                [],
            ):
                part["quality"] = span["quality"]
                segments.append(part)
        segments.sort(key=lambda s: s["start"])
        cost = None if record["manual_cost"] is None else Decimal(record["manual_cost"])
        allocated = Decimal(0)
        with localcontext() as ctx:
            ctx.prec = 36
            for index, part in enumerate(segments):
                cumulative = (
                    None
                    if cost is None
                    else (
                        cost
                        if index == len(segments) - 1
                        else cost
                        * elapsed(start, instant(part["end"]))
                        / elapsed(start, end)
                    )
                )
                part["cost"] = (
                    None if cumulative is None else str(cumulative - allocated)
                )
                part.update(
                    unit_price=None, cost_basis="unknown" if cost is None else "manual"
                )
                marks = set(part["quality"]) - {"price_unknown", "missing_price"}
                part["quality"] = sorted(
                    marks
                    | {"manual", "estimated"}
                    | ({"price_unknown"} if cost is None else set())
                )
                if cumulative is not None:
                    allocated = cumulative
        return segments

    def _historical_prices(self, point_id, start, end):
        versions = self.ledger.list_price_versions(point_id)
        persistent = {
            p["at"]: p["price"]
            for p in versions
            if "price" in p and instant(p["at"]) < end
        }
        fallback, observed = {}, {}
        pruned_gaps = self.ledger.get_checkpoint("_price_gaps:" + point_id) or []
        for gap in pruned_gaps:
            fallback[gap["start"]] = None
        for observation in self.ledger.list_intervals(
            point_id, start.isoformat(), end.isoformat()
        ):
            left, right = observation["start"], observation["end"]
            context = [(at, 1, price) for at, price in persistent.items() if at <= left]
            context.extend(
                (gap["start"], -1, None) for gap in pruned_gaps if gap["start"] <= left
            )
            context.extend(
                (at, 0, price) for at, price in observation["prices"] if at <= left
            )
            if context:
                observed[left] = max(context, key=lambda item: (item[0], item[1]))[2]
            else:
                fallback[left] = None
            for at, price in observation["prices"]:
                if left < at < right:
                    observed[at] = price
            if not any(at <= right for at in persistent):
                fallback[right] = None
        timeline = {**fallback, **observed, **persistent}
        ordered = sorted(timeline.items())
        anchor = [(at, price) for at, price in ordered if instant(at) <= start]
        return anchor[-1:] + [
            (at, price) for at, price in ordered if start < instant(at) < end
        ]

    def start(
        self,
        point_id,
        identity_id,
        at: datetime,
        request_id: str,
        source="manual",
        timezone="Asia/Shanghai",
    ):
        at = instant(at).isoformat()
        ZoneInfo(timezone)

        def operation():
            self._references(point_id, identity_id)
            overlaps = self.ledger.overlaps(point_id, at, None)
            if overlaps:
                raise ValueError(f"Record interval conflict: {overlaps[0]}")
            record = dict(
                id=uuid4().hex,
                point_id=point_id,
                identity_id=identity_id,
                start=at,
                end=None,
                timezone=timezone,
                source=source,
                status="active",
                revision=1,
                note="",
            )
            record, segments, _ = self._build(record)
            self.ledger.save_record(record, segments)
            return record

        return self._request(
            request_id,
            ["start", point_id, identity_id, at, source, timezone],
            operation,
        )

    def end(self, record_id, at: datetime, request_id: str):
        at = instant(at).isoformat()

        def operation():
            record = self._record(record_id)
            if record["status"] != "active" or at <= record["start"]:
                raise ValueError("End must follow the active record start")
            record.update(end=at, status="ended", revision=record["revision"] + 1)
            record, segments, _ = self._build(record)
            self.ledger.save_record(record, segments)
            return record

        return self._request(request_id, ["end", record_id, at], operation)

    def _interval_data(self, point_id, start, end, energy, prices, quality):
        start, end = instant(start), instant(end)
        energy = decimal_value(energy, nonnegative=True)
        prices = [
            (instant(at), None if price is None else decimal_value(price))
            for at, price in prices
        ]
        split_interval(start, end, energy, "UTC", prices)
        point = self.ledger.get_point(point_id)
        if point is None:
            raise ValueError("Unknown point")
        gap = elapsed(start, end) > Decimal(
            str(point.get("max_interval_seconds", 600))
        ) or bool(set(quality) & {"unavailable", "missing_energy", "gap", "reset"})
        return dict(
            id=sha256(
                encode([point_id, start.isoformat(), end.isoformat()]).encode()
            ).hexdigest(),
            point_id=point_id,
            start=start.isoformat(),
            end=end.isoformat(),
            energy_kwh=str(energy),
            prices=[
                [at.isoformat(), None if price is None else str(price)]
                for at, price in prices
            ],
            quality=sorted(set(quality)),
            gap=gap,
        )

    @contextmanager
    def batch_refresh(self):
        """Rebuild each affected record once and roll back failed nested batches."""
        parent = self._refresh_pending
        self._refresh_pending = set() if parent is None else set(parent)
        try:
            with self.ledger.transaction():
                yield
                if parent is None:
                    for record_id in sorted(self._refresh_pending):
                        self._refresh_record(self.ledger.get_record(record_id))
                else:
                    parent.update(self._refresh_pending)
        finally:
            self._refresh_pending = parent

    def _refresh_record(self, record):
        if (
            record is None
            or record["status"] == "void"
            or record.get("manual_override")
        ):
            return
        previous = dict(record)
        old_segments = self.ledger.list_segments(record["id"])
        record, segments, _ = self._build(record)
        if record == previous and segments == old_segments:
            return
        record["revision"] += 1
        self.ledger.save_record(record, segments, audit=False)
        if record["status"] == "ended":
            self.ledger.save_revision(record["id"])

    def _refresh(self, point_id, start, end, observation=None):
        for record in self.ledger.list_records(point_id=point_id):
            if (
                record.get("manual_override")
                or record["start"] >= end
                or (record["end"] and record["end"] <= start)
            ):
                continue
            if self._refresh_pending is not None:
                self._refresh_pending.add(record["id"])
            elif observation is not None and self._append_observation(
                record, observation
            ):
                continue
            else:
                self._refresh_record(record)

    def add_interval(self, point_id, start, end, energy: Decimal, prices, quality=()):
        data = self._interval_data(point_id, start, end, energy, prices, quality)
        with self.ledger.transaction():
            if not self.ledger.put_interval(data):
                return
            self._refresh(point_id, data["start"], data["end"], data)

    def replace_gap(self, point_id, start, end, intervals: list[dict]):
        start, end = instant(start).isoformat(), instant(end).isoformat()
        gap_id = sha256(encode([point_id, start, end]).encode()).hexdigest()
        replacements = [
            self._interval_data(
                point_id,
                i["start"],
                i["end"],
                i["energy_kwh"],
                i["prices"],
                i.get("quality", ()),
            )
            for i in intervals
        ]
        with self.ledger.transaction():
            self.ledger.resolve_gap(gap_id, replacements)
            self._refresh(point_id, start, end)

    def reassign(self, record_id, identity_id, expected_revision: int):
        with self.ledger.transaction():
            record = self._record(record_id, expected_revision)
            self._references(record["point_id"], identity_id, record)
            record.update(identity_id=identity_id, revision=record["revision"] + 1)
            self.ledger.save_record(record, self.ledger.list_segments(record_id))
            return record

    def void(self, record_id, expected_revision: int):
        with self.ledger.transaction():
            record = self._record(record_id, expected_revision)
            record.update(status="void", revision=record["revision"] + 1)
            self.ledger.save_record(record, self.ledger.list_segments(record_id))
            return record

    def _basis_fingerprint(self, record, dependencies):
        current = self.ledger.get_record(record["id"])
        basis = {
            "point": self.ledger.get_point(record["point_id"]),
            "identity": self.ledger.get_identity(record["identity_id"]),
            "record_revision": current["revision"] if current else None,
        }
        basis["point"] = {
            key: value for key, value in basis["point"].items() if key != "price"
        }
        if dependencies.get("intervals"):
            basis["intervals"] = self.ledger.list_intervals(
                record["point_id"], record["start"], record["end"]
            )
        if dependencies.get("prices"):
            basis["prices"] = self.price_basis(
                record["point_id"], instant(record["start"]), instant(record["end"])
            )
        return sha256(encode(basis).encode()).hexdigest()

    def preview(self, data: dict):
        with self.ledger.transaction():
            original = (
                self._record(data["record_id"], data.get("expected_revision"))
                if data.get("record_id")
                else None
            )
            if original and (
                "expected_revision" not in data or original["status"] == "active"
            ):
                raise ValueError(
                    "Editing requires an ended record and expected revision"
                )
            merged = {**(original or {}), **data}
            start, end = instant(merged["start"]), instant(merged["end"])
            if end <= start or end > datetime.now(UTC):
                raise ValueError(
                    "Historical end must follow start and not be in the future"
                )
            timezone = merged.get("timezone", "Asia/Shanghai")
            ZoneInfo(timezone)
            self._references(merged["point_id"], merged["identity_id"], original)
            record = dict(
                id=original["id"] if original else uuid4().hex,
                point_id=merged["point_id"],
                identity_id=merged["identity_id"],
                start=start.isoformat(),
                end=end.isoformat(),
                timezone=timezone,
                source="history",
                status="ended",
                revision=original["revision"] + 1 if original else 1,
                note=merged.get("note", ""),
            )
            basis_changed = bool(
                set(data)
                & {
                    "start",
                    "end",
                    "point_id",
                    "timezone",
                    "energy_kwh",
                    "cost",
                    "prices",
                }
            )
            dependencies = {"intervals": False, "prices": False}
            if original and not basis_changed:
                record = {**original, **record, "source": original["source"]}
                segments = self.ledger.list_segments(original["id"])
                coverage = [
                    {"start": s["start"], "end": s["end"]}
                    for s in segments
                    if s.get("observation_id")
                ]
            elif "energy_kwh" in data or (original and original.get("manual_override")):
                energy = decimal_value(
                    data.get(
                        "energy_kwh",
                        original.get("manual_energy") if original else None,
                    ),
                    nonnegative=True,
                )
                record.update(
                    source="manual", manual_override=True, manual_energy=str(energy)
                )
                explicit_cost = "cost" in data or (
                    original and "manual_cost" in original
                )
                prices = data.get("prices", [])
                if not prices and not explicit_cost:
                    dependencies["prices"] = True
                    prices = self.price_resolver(record["point_id"], start, end)
                prices = [
                    (instant(at), None if price is None else decimal_value(price))
                    for at, price in prices
                ]
                segments = split_interval(
                    start, end, energy, timezone, [] if explicit_cost else prices
                )
                if explicit_cost:
                    cost = data.get(
                        "cost", original.get("manual_cost") if original else None
                    )
                    cost = None if cost is None else decimal_value(cost)
                    record["manual_cost"] = None if cost is None else str(cost)
                    allocated = Decimal(0)
                    with localcontext() as ctx:
                        ctx.prec = 36
                        for index, part in enumerate(segments):
                            cumulative = (
                                None
                                if cost is None
                                else (
                                    cost
                                    if index == len(segments) - 1
                                    else cost
                                    * elapsed(start, instant(part["end"]))
                                    / elapsed(start, end)
                                )
                            )
                            part["cost"] = (
                                None
                                if cumulative is None
                                else str(cumulative - allocated)
                            )
                            part.update(
                                unit_price=None,
                                cost_basis="unknown" if cost is None else "manual",
                            )
                            part["quality"] = ["price_unknown"] if cost is None else []
                            if cumulative is not None:
                                allocated = cumulative
                for part in segments:
                    part["quality"] = sorted(
                        set(part["quality"]) | {"manual", "estimated"}
                    )
                record = totals(record, segments)
                coverage = []
            else:
                dependencies["intervals"] = True
                if "cost" in data or (original and original.get("manual_fee_override")):
                    cost = data.get(
                        "cost", original.get("manual_cost") if original else None
                    )
                    record.update(
                        manual_fee_override=True,
                        manual_cost=None if cost is None else str(decimal_value(cost)),
                    )
                record, segments, coverage = self._build(record)
                record["quality"] = sorted(
                    set(record["quality"]) - {"pending_settlement"}
                )
                for span in record["quality_spans"]:
                    span["quality"] = sorted(
                        set(span["quality"]) - {"pending_settlement"}
                    )
            overlaps = self.ledger.overlaps(
                record["point_id"], record["start"], record["end"], record["id"]
            )
            result = dict(
                record=record,
                segments=segments,
                coverage=coverage,
                overlaps=overlaps,
                basis_version=self.ledger.data_version(),
                expected_revision=original["revision"] if original else None,
                basis_dependencies=dependencies,
                basis_fingerprint=self._basis_fingerprint(record, dependencies),
            )
            token = uuid4().hex
            stored = {
                "payload": result,
                "digest": sha256(encode(result).encode()).hexdigest(),
            }
            self.ledger.put_preview(token, stored)
            return {**result, "token": token}

    def commit_preview(self, token: str, request_id: str):
        def operation():
            stored = self.ledger.get_preview(token)
            if not stored:
                raise ValueError("Unknown preview")
            data = stored["payload"]
            if stored["digest"] != sha256(encode(data).encode()).hexdigest():
                raise ValueError("Preview is stale; refresh it")
            record = data["record"]
            if data.get("basis_fingerprint") != self._basis_fingerprint(
                record, data.get("basis_dependencies", {})
            ):
                raise ValueError("Preview is stale; refresh it")
            original = None
            if data["expected_revision"] is not None:
                original = self._record(record["id"], data["expected_revision"])
            self._references(record["point_id"], record["identity_id"], original)
            if instant(record["end"]) > datetime.now(UTC):
                raise ValueError("Historical end is in the future")
            self.ledger.save_record(record, data["segments"])
            return record

        return self._request(request_id, ["commit_preview", token], operation)
