"""Read current record revisions, independent of Home Assistant Recorder."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from .accounting import instant
from .core.buckets import bucket_windows, choose_bucket_period
from .core.tariffs import elapsed
from .record_views import record_view


def calendar_bounds(label, timezone):
    """Interpret a calendar label in the original record's accounting timezone."""
    if len(label) not in (4, 7, 10):
        raise ValueError("Invalid calendar label")
    value = label + {4: "-01-01", 7: "-01", 10: ""}[len(label)]
    start = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=ZoneInfo(timezone))
    if start.strftime("%Y-%m-%d") != value:
        raise ValueError("Invalid calendar label")
    if len(label) == 4:
        end = start.replace(year=start.year + 1)
    elif len(label) == 7:
        end = start.replace(
            year=start.year + (start.month == 12), month=start.month % 12 + 1
        )
    else:
        end = start + timedelta(days=1)
    return instant(start), instant(end)


def summarize(
    ledger,
    start,
    end,
    identity_id=None,
    point_id=None,
    *,
    calendar=None,
    bucket_period="auto",
    timezone="UTC",
    include_records=False,
    max_records=None,
    max_segments=None,
    cache=None,
):
    if calendar is not None and (start is not None or end is not None):
        raise ValueError("Calendar and absolute range are mutually exclusive")
    start, end = instant(start) if start else None, instant(end) if end else None
    if calendar is not None:
        calendar_bounds(calendar, "UTC")
    if start and end and end <= start:
        raise ValueError("Query end must follow start")
    period = choose_bucket_period(
        bucket_period, calendar=calendar, start=start, end=end, timezone=timezone
    )
    absolute_start, absolute_end = start, end
    result = dict(
        energy_kwh="0",
        known_cost="0",
        cost_complete=True,
        active_count=0,
        completed_count=0,
        matched_count=0,
        has_energy_data=False,
        has_known_cost=False,
        bucket_period=period,
        quality=[],
        buckets=[],
    )
    energy, cost, quality, buckets = Decimal(0), Decimal(0), set(), {}
    hourly_windows = {}
    calendar_windows = {}
    contributions, segment_count = [], 0
    if include_records:
        cache = None
    query = (start, end, identity_id, point_id, calendar, period, timezone)
    if cache is not None and cache.get("query") != query:
        cache.clear()

    def windows_for(a, b, record_timezone):
        if period != "hour":
            windows = calendar_windows.get(record_timezone)
            if windows is None or windows[0].start > a or windows[-1].end < b:
                windows = bucket_windows(a, b, record_timezone, period)
                calendar_windows[record_timezone] = windows
            return [window for window in windows if window.start < b and window.end > a]
        # Cache full UTC-date spans only for this query. Window boundaries still
        # use the record's local calendar, including folds and clock changes.
        left = a.replace(hour=0, minute=0, second=0, microsecond=0)
        right = (b - timedelta(microseconds=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        key = (record_timezone, left, right)
        if key not in hourly_windows:
            hourly_windows[key] = bucket_windows(left, right, record_timezone, period)
        return [
            window
            for window in hourly_windows[key]
            if window.start < b and window.end > a
        ]

    def bucket(window):
        if window.key not in buckets:
            item = dict(
                key=window.key,
                label=window.label,
                energy=Decimal(0),
                cost=Decimal(0),
                cost_complete=True,
                quality=set(),
                has_energy_data=False,
                has_known_cost=False,
            )
            if period == "hour":
                item.update(
                    start=window.start.isoformat(),
                    end=window.end.isoformat(),
                    timezone=window.timezone,
                )
            buckets[window.key] = item
        return buckets[window.key]

    with ledger.transaction(), localcontext() as ctx:
        ctx.prec = 36
        records = ledger.list_records(point_id, identity_id)
        position, resume, tail, stable = 0, None, None, None
        if cache is not None:
            # Metadata comparisons never regroup the original Decimal additions.
            signatures = [
                (
                    record["id"],
                    record["revision"],
                    ledger.segment_generation(record["id"]),
                )
                for record in records
            ]
            tail_fields = (
                "id",
                "point_id",
                "identity_id",
                "start",
                "end",
                "status",
                "timezone",
                "manual_override",
                "manual_fee_override",
                "quality_spans",
            )
            tail_record = (
                {
                    **{field: records[-1].get(field) for field in tail_fields},
                    "_accounted_until": records[-1].get("_accounted_until"),
                    "_segment_count": records[-1].get("_segment_count"),
                }
                if records
                else None
            )
            stable_position = next(
                (i for i, record in enumerate(records) if record["status"] == "active"),
                max(0, len(records) - 1),
            )
            previous_stable = cache.get("stable")
            if (
                previous_stable is not None
                and len(previous_stable[0]) == stable_position
                and previous_stable[0] == signatures[:stable_position]
            ):
                stable = previous_stable
            for checkpoint in sorted(
                (value for name in ("full", "stable") if (value := cache.get(name))),
                key=lambda value: len(value[0]),
                reverse=True,
            ):
                count = len(checkpoint[0])
                if checkpoint[0] == signatures[:count]:
                    position = count
                elif count and count == len(records) and checkpoint[2] is not None:
                    previous = checkpoint[2]
                    current = records[-1]
                    if (
                        checkpoint[0][:-1] != signatures[:-1]
                        or checkpoint[0][-1][2] != signatures[-1][2]
                        or previous["status"] != "active"
                        or previous.get("manual_override")
                        or previous.get("manual_fee_override")
                        or not previous.get("_accounted_until")
                        or previous.get("_segment_count") is None
                        or current.get("_segment_count", 0)
                        <= previous["_segment_count"]
                        or any(
                            previous[field] != current.get(field)
                            for field in tail_fields
                        )
                    ):
                        continue
                    # A stable generation proves the old positions were not
                    # replaced, even if count and accounting horizon both grew.
                    tail = ledger.list_segments(
                        current["id"], start_position=previous["_segment_count"]
                    )
                    if (
                        len(tail)
                        != current["_segment_count"] - previous["_segment_count"]
                        or not tail
                        or tail[0]["start"] != previous["_accounted_until"]
                        or tail[-1]["end"] != current.get("_accounted_until")
                        or any(a["end"] != b["start"] for a, b in zip(tail, tail[1:]))
                    ):
                        tail = None
                        continue
                    position = resume = count - 1
                else:
                    continue
                result, energy, cost, quality, buckets = deepcopy(checkpoint[1])
                break
        for index, record in enumerate(records[position:], position):
            if cache is not None and index == stable_position and resume != index:
                stable = (
                    signatures[:index],
                    deepcopy((result, energy, cost, quality, buckets)),
                    None,
                )
            start, end = (
                calendar_bounds(calendar, record["timezone"])
                if calendar is not None
                else (absolute_start, absolute_end)
            )
            begins = instant(record["start"])
            finishes = instant(record["end"]) if record["end"] else None
            if (end and begins >= end) or (start and finishes and finishes <= start):
                continue
            if index != resume:
                result["matched_count"] += 1
            if include_records and max_records is not None:
                if result["matched_count"] > max_records:
                    raise ValueError("export_too_large")
            row_energy, row_cost, row_quality = Decimal(0), Decimal(0), set()
            row_complete, row_has_energy, row_has_cost = True, False, False
            active = record["status"] == "active"
            if active and index != resume:
                result["active_count"] += 1
                quality.add("provisional")
                row_quality.add("provisional")
            elif (
                not active
                and (start is None or begins >= start)
                and (end is None or begins < end)
            ):
                result["completed_count"] += 1
            for span in record.get("quality_spans", []) if index != resume else []:
                a = (
                    max(instant(span["start"]), start)
                    if start
                    else instant(span["start"])
                )
                b = min(instant(span["end"]), end) if end else instant(span["end"])
                if a >= b:
                    continue
                quality.update(span["quality"])
                result["cost_complete"] = False
                row_quality.update(span["quality"])
                row_complete = False
                for window in windows_for(a, b, record["timezone"]):
                    item = bucket(window)
                    item["cost_complete"] = False
                    item["quality"].update(span["quality"])
                    if active:
                        item["quality"].add("provisional")
            # Raw ledger segments preserve the actual sample distribution.
            parts = tail if index == resume else ledger.list_segments(record["id"])
            if include_records and max_segments is not None:
                segment_count += len(parts)
                if segment_count > max_segments:
                    raise ValueError("export_too_large")
            for part in parts:
                left, right = instant(part["start"]), instant(part["end"])
                a, b = (
                    max(left, start) if start else left,
                    min(right, end) if end else right,
                )
                if b <= a:
                    continue
                weight = elapsed(a, b) / elapsed(left, right)
                amount = Decimal(part["energy_kwh"]) * weight
                fee = (
                    Decimal(part["cost"]) * weight if part["cost"] is not None else None
                )
                windows = windows_for(a, b, record["timezone"])
                marks = set(part["quality"])
                if active:
                    marks.add("provisional")
                if a != left or b != right or len(windows) > 1:
                    marks.add("estimated")
                if fee is None:
                    marks.add("missing_price")
                    result["cost_complete"] = False
                marks.discard("price_unknown")
                quality.update(marks)
                energy += amount
                cost += fee if fee is not None else Decimal(0)
                result["has_energy_data"] = True
                result["has_known_cost"] |= fee is not None
                if include_records:
                    # Row totals never feed back into the ordered global sums.
                    row_energy += amount
                    row_cost += fee if fee is not None else Decimal(0)
                    row_quality.update(marks)
                    row_complete &= fee is not None
                    row_has_energy = True
                    row_has_cost |= fee is not None
                allocated_energy, allocated_cost = Decimal(0), Decimal(0)
                for index, window in enumerate(windows):
                    item = bucket(window)
                    fraction = elapsed(a, min(b, window.end)) / elapsed(a, b)
                    cumulative_energy = (
                        amount if index == len(windows) - 1 else amount * fraction
                    )
                    item["energy"] += cumulative_energy - allocated_energy
                    allocated_energy = cumulative_energy
                    if fee is not None:
                        cumulative_cost = (
                            fee if index == len(windows) - 1 else fee * fraction
                        )
                        item["cost"] += cumulative_cost - allocated_cost
                        allocated_cost = cumulative_cost
                    item["has_energy_data"] = True
                    item["has_known_cost"] |= fee is not None
                    item["cost_complete"] &= fee is not None
                    item["quality"].update(marks)
            if include_records:
                range_end = min(finishes, end) if finishes and end else finishes or end
                contributions.append(
                    dict(
                        record=record_view(record, parts),
                        range_start=(
                            max(begins, start) if start else begins
                        ).isoformat(),
                        range_end=range_end.isoformat() if range_end else None,
                        energy_kwh=str(row_energy),
                        known_cost=str(row_cost),
                        cost_complete=row_complete,
                        quality=sorted(row_quality),
                        has_energy_data=row_has_energy,
                        has_known_cost=row_has_cost,
                    )
                )
        if cache is not None:
            # Bucket remainder correction below mutates the public projection.
            # Resume only from these unfinalized values and their original order.
            full = (
                signatures,
                deepcopy((result, energy, cost, quality, buckets)),
                deepcopy(tail_record),
            )
    if cache is not None:
        cache.update(query=query, stable=stable, full=full)
    ordered = sorted(
        buckets.values(), key=lambda item: (item.get("start", item["key"]), item["key"])
    )
    # Match the selected totals despite Decimal addition being non-associative.
    # Keep true-zero and unknown buckets unchanged; the last nonzero bucket owns
    # the aggregate remainder, after summing its predecessors in public order.
    with localcontext() as ctx:
        ctx.prec = 36
        for field, total in (("energy", energy), ("cost", cost)):
            last = next(
                (
                    index
                    for index in range(len(ordered) - 1, -1, -1)
                    if ordered[index][field] != 0
                ),
                None,
            )
            if last is None:
                continue
            prefix = sum((item[field] for item in ordered[:last]), Decimal(0))
            # Subtract exactly, including cancellation between differently sized
            # values; adding this remainder to the prefix rounds back to total.
            with localcontext() as exact:
                exact.prec = (
                    max(total.adjusted(), prefix.adjusted())
                    - min(total.as_tuple().exponent, prefix.as_tuple().exponent)
                    + 2
                )
                ordered[last][field] = total - prefix
    result.update(
        energy_kwh=str(energy),
        known_cost=str(cost),
        quality=sorted(quality),
        buckets=[
            {
                **{
                    k: v
                    for k, v in item.items()
                    if k not in ("energy", "cost", "quality")
                },
                "energy_kwh": str(item["energy"]),
                "known_cost": str(item["cost"]),
                "quality": sorted(item["quality"]),
            }
            for item in ordered
        ],
    )
    if include_records:
        result["records"] = contributions
    return result
