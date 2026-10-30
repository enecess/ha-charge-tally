"""Repeated sample summaries reuse complete calendar windows."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.charge_tally import queries
from custom_components.charge_tally.accounting import Accounting, totals
from custom_components.charge_tally.ledger import Ledger


@pytest.mark.parametrize("period", ["day", "month", "year"])
def test_calendar_windows_are_reused_across_samples(tmp_path, monkeypatch, period):
    ledger = Ledger(str(tmp_path / "ledger.sqlite3"))
    ledger.put_identity({"id": "i", "name": "Car"})
    ledger.put_point({"id": "p", "name": "Point"})
    accounting = Accounting(ledger)
    start = datetime(2025, 12, 31, 23, 59, tzinfo=UTC)
    record = accounting.start("p", "i", start, "start", timezone="UTC")
    segments = [
        {
            "start": (start + timedelta(seconds=index)).isoformat(),
            "end": (start + timedelta(seconds=index + 1)).isoformat(),
            "energy_kwh": "0.001",
            "cost": "-0.002",
            "quality": [],
        }
        for index in range(120)
    ]
    ledger.save_record(record, segments, audit=False)
    calls = []
    original = queries.bucket_windows

    def observed(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(queries, "bucket_windows", observed)
    result = queries.summarize(ledger, None, None, bucket_period=period)
    assert Decimal(result["energy_kwh"]) == Decimal("0.120")
    assert Decimal(result["known_cost"]) == Decimal("-0.240")
    assert [Decimal(bucket["energy_kwh"]) for bucket in result["buckets"]] == [
        Decimal("0.060"),
        Decimal("0.060"),
    ]
    assert len(calls) == 2
    ledger.close()


def summary_record(ledger, point, start, parts, *, active=False, timezone="UTC"):
    record = Accounting(ledger).start(
        point, "i", start, point + start.isoformat(), timezone=timezone
    )
    record.update(
        status="active" if active else "ended",
        end=None if active else parts[-1]["end"],
        _segment_count=len(parts),
        _accounted_until=parts[-1]["end"],
    )
    totals(record, parts)
    ledger.save_record(record, parts, audit=False)
    return record


def summary_parts(start, count, *, energy="0.001", cost="-0.002"):
    return [
        {
            "start": (start + timedelta(seconds=index)).isoformat(),
            "end": (start + timedelta(seconds=index + 1)).isoformat(),
            "energy_kwh": energy,
            "cost": cost,
            "quality": [],
        }
        for index in range(count)
    ]


@pytest.mark.parametrize("historical", [True, False])
def test_summary_append_reads_only_new_positions(tmp_path, monkeypatch, historical):
    """Re-reading a cached historical prefix or current positions is a regression."""
    ledger = Ledger(str(tmp_path / "ledger.sqlite3"))
    ledger.put_identity({"id": "i", "name": "Car"})
    ledger.put_point({"id": "p", "name": "Point"})
    start = datetime(2026, 1, 1, tzinfo=UTC)
    record = summary_record(
        ledger, "p", start, summary_parts(start, 20_000), active=not historical
    )
    if historical:
        start += timedelta(days=1)
        record = summary_record(
            ledger, "p", start, summary_parts(start, 1), active=True
        )
    cache = {}
    queries.summarize(ledger, None, None, cache=cache)
    original = ledger.list_segments
    reads = []

    def observed(record_id, *, start_position=0):
        parts = original(record_id, start_position=start_position)
        reads.append((record_id, start_position, len(parts)))
        return parts

    monkeypatch.setattr(ledger, "list_segments", observed)
    new = summary_parts(datetime.fromisoformat(record["_accounted_until"]), 1)
    updated = totals(dict(record), new, record["quality"], append=True)
    updated.update(
        revision=record["revision"] + 1,
        _segment_count=record["_segment_count"] + 1,
        _accounted_until=new[-1]["end"],
    )
    ledger.append_record_segments(updated, new, record["_segment_count"])
    cached = queries.summarize(ledger, None, None, cache=cache)
    assert reads == [(record["id"], record["_segment_count"], 1)]
    assert Decimal(cached["energy_kwh"]) == Decimal(
        "20.002" if historical else "20.001"
    )
    assert cached["active_count"] == 1
    assert cached["matched_count"] == (2 if historical else 1)
    assert cached == queries.summarize(ledger, None, None)
    ledger.close()


def test_two_active_points_keep_the_stable_history_prefix(tmp_path, monkeypatch):
    ledger = Ledger(str(tmp_path / "ledger.sqlite3"))
    ledger.put_identity({"id": "i", "name": "Car"})
    for point in ("p", "q"):
        ledger.put_point({"id": point, "name": point})
    start = datetime(2026, 1, 1, tzinfo=UTC)
    old = summary_record(ledger, "p", start, summary_parts(start, 20_000))
    start += timedelta(days=1)
    first = summary_record(ledger, "p", start, summary_parts(start, 1), active=True)
    summary_record(
        ledger,
        "q",
        start + timedelta(seconds=1),
        summary_parts(start + timedelta(seconds=1), 1),
        active=True,
    )
    cache = {}
    queries.summarize(ledger, None, None, cache=cache)
    ledger.save_record(first, summary_parts(start, 2, energy="2"), audit=False)
    original = ledger.list_segments
    reads = []

    def observed(record_id, *, start_position=0):
        parts = original(record_id, start_position=start_position)
        reads.append((record_id, len(parts)))
        return parts

    monkeypatch.setattr(ledger, "list_segments", observed)
    cached = queries.summarize(ledger, None, None, cache=cache)
    assert old["id"] not in [record_id for record_id, _ in reads]
    assert sum(count for _, count in reads) == 3
    assert cached["energy_kwh"] == "24.001"
    assert cached["active_count"] == 2
    assert cached == queries.summarize(ledger, None, None)
    ledger.close()


def test_summary_replacement_cannot_masquerade_as_a_contiguous_append(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.sqlite3"))
    ledger.put_identity({"id": "i", "name": "Car"})
    ledger.put_point({"id": "p", "name": "Point"})
    start = datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC)
    record = summary_record(
        ledger, "p", start, summary_parts(start, 2, energy="1"), active=True
    )
    cache = {}
    queries.summarize(ledger, None, None, bucket_period="day", cache=cache)
    replacement = summary_parts(start, 3, energy="2")
    replacement[0]["energy_kwh"] = "7"
    record.update(
        revision=record["revision"] + 1,
        _segment_count=3,
        _accounted_until=replacement[-1]["end"],
    )
    totals(record, replacement)
    ledger.save_record(record, replacement, audit=False)
    cached = queries.summarize(ledger, None, None, bucket_period="day", cache=cache)
    assert cached["energy_kwh"] == "11"
    assert [bucket["energy_kwh"] for bucket in cached["buckets"]] == ["7", "4"]
    assert cached == queries.summarize(ledger, None, None, bucket_period="day")
    ledger.close()


@pytest.mark.parametrize("period", ["hour", "day", "month", "year"])
@pytest.mark.parametrize("timezone", ["UTC", "America/New_York", "Asia/Shanghai"])
def test_summary_checkpoints_preserve_ordered_decimal_state(tmp_path, period, timezone):
    """Rounded row totals or finalized bucket reuse loses the tiny remainder."""
    ledger = Ledger(str(tmp_path / "ledger.sqlite3"))
    ledger.put_identity({"id": "i", "name": "Car"})
    ledger.put_point({"id": "p", "name": "Point"})
    start = datetime(2026, 10, 31, 23, 59, 58, tzinfo=UTC)
    summary_record(
        ledger,
        "p",
        start,
        summary_parts(start, 1, energy="1E+40", cost="2"),
        timezone="UTC",
    )
    start += timedelta(seconds=1)
    parts = summary_parts(start, 2, energy="-1E+40", cost="-3")
    parts[1].update(energy_kwh="1E-40", cost="0")
    record = summary_record(ledger, "p", start, parts, active=True, timezone=timezone)
    cache = {}
    options = {"bucket_period": period, "timezone": timezone}
    warm = queries.summarize(ledger, None, None, cache=cache, **options)
    assert warm["energy_kwh"] == "1E-40"
    # Mutating a public response must not alter either raw checkpoint.
    warm["buckets"][0]["energy_kwh"] = "999"
    for index in range(2):
        tail = summary_parts(
            datetime.fromisoformat(record["_accounted_until"]),
            1,
            energy="3E-40",
            cost=None,
        )
        updated = totals(dict(record), tail, record["quality"], append=True)
        updated.update(
            revision=record["revision"] + 1,
            _segment_count=record["_segment_count"] + 1,
            _accounted_until=tail[-1]["end"],
        )
        ledger.append_record_segments(updated, tail, record["_segment_count"])
        record = updated
        cached = queries.summarize(ledger, None, None, cache=cache, **options)
        assert cached["energy_kwh"] == ("4E-40" if index == 0 else "7E-40")
        assert cached["known_cost"] == "-1"
        assert cached["cost_complete"] is False
        assert cached["quality"] == ["missing_price", "provisional"]
        assert cached == queries.summarize(ledger, None, None, **options)
    for arguments in (
        {"calendar": "2026-11-01"},
        {"calendar": "2026-10"},
        {
            "start": start + timedelta(microseconds=500_000),
            "end": start + timedelta(seconds=3, microseconds=500_000),
        },
    ):
        bounds = {"start": None, "end": None, **arguments}
        assert queries.summarize(ledger, cache=cache, **bounds, **options) == (
            queries.summarize(ledger, **bounds, **options)
        )
    ledger.close()


@pytest.mark.parametrize(
    "change", ["gap", "ended", "edit", "reassign", "void", "edit_and_void"]
)
def test_summary_rebuilds_changed_suffix(tmp_path, monkeypatch, change):
    """Earlier changes must invalidate dependent aggregates and record counters."""
    ledger = Ledger(str(tmp_path / "ledger.sqlite3"))
    ledger.put_identity({"id": "i", "name": "Car"})
    ledger.put_identity({"id": "other", "name": "Other"})
    ledger.put_point({"id": "p", "name": "Point"})
    start = datetime(2026, 1, 1, tzinfo=UTC)
    first = summary_record(ledger, "p", start, summary_parts(start, 1, energy="2"))
    start += timedelta(days=1)
    record = summary_record(
        ledger, "p", start, summary_parts(start, 1, energy="3"), active=True
    )
    cache = {}
    queries.summarize(ledger, None, None, identity_id="i", cache=cache)
    if change in ("edit", "edit_and_void"):
        first["revision"] += 1
        ledger.save_record(
            first, summary_parts(start - timedelta(days=1), 1, energy="7"), audit=False
        )
        if change == "edit_and_void":
            record.update(status="void", revision=record["revision"] + 1)
            ledger.save_record(record, summary_parts(start, 1, energy="3"), audit=False)
    else:
        record["revision"] += 1
        if change == "gap":
            record["quality_spans"] = [
                {
                    "start": start.isoformat(),
                    "end": (start + timedelta(seconds=2)).isoformat(),
                    "quality": ["missing_energy"],
                }
            ]
        elif change == "ended":
            record.update(
                status="ended", end=(start + timedelta(seconds=1)).isoformat()
            )
        elif change == "reassign":
            record["identity_id"] = "other"
        else:
            record["status"] = "void"
        ledger.save_record(record, summary_parts(start, 1, energy="3"), audit=False)
    original = ledger.list_segments
    reads = []

    def observed(record_id, *, start_position=0):
        parts = original(record_id, start_position=start_position)
        reads.append(record_id)
        return parts

    monkeypatch.setattr(ledger, "list_segments", observed)
    cached = queries.summarize(ledger, None, None, identity_id="i", cache=cache)
    assert (first["id"] in reads) is (change in ("edit", "edit_and_void"))
    assert (
        Decimal(cached["energy_kwh"])
        == {
            "gap": 5,
            "ended": 5,
            "edit": 10,
            "reassign": 2,
            "void": 2,
            "edit_and_void": 7,
        }[change]
    )
    assert cached["active_count"] == (
        0 if change in ("ended", "reassign", "void", "edit_and_void") else 1
    )
    if change == "gap":
        assert cached["cost_complete"] is False
        assert cached["quality"] == ["missing_energy", "provisional"]
    assert cached == queries.summarize(ledger, None, None, identity_id="i")
    ledger.close()


@pytest.mark.parametrize("operation", ["void", "reassign"])
def test_removing_earlier_record_does_not_resume_stable_checkpoint_as_tail(
    tmp_path, operation
):
    ledger = Ledger(str(tmp_path / "ledger.sqlite3"))
    ledger.put_identity({"id": "i", "name": "Car"})
    ledger.put_identity({"id": "other", "name": "Other"})
    ledger.put_point({"id": "p", "name": "Point"})
    start = datetime(2026, 1, 1, tzinfo=UTC)
    first = summary_record(ledger, "p", start, summary_parts(start, 1, energy="2"))
    start += timedelta(days=1)
    summary_record(ledger, "p", start, summary_parts(start, 1, energy="1"), active=True)
    cache = {}
    options = {"identity_id": "i", "bucket_period": "day"}
    assert (
        queries.summarize(ledger, None, None, cache=cache, **options)["energy_kwh"]
        == "3"
    )
    accounting = Accounting(ledger)
    if operation == "void":
        accounting.void(first["id"], first["revision"])
    else:
        accounting.reassign(first["id"], "other", first["revision"])
    uncached = queries.summarize(ledger, None, None, **options)
    assert uncached["energy_kwh"] == "1"
    cached = queries.summarize(ledger, None, None, cache=cache, **options)
    assert cached == uncached
    assert cached["matched_count"] == cached["active_count"] == 1
    assert cached["completed_count"] == 0
    assert [bucket["energy_kwh"] for bucket in cached["buckets"]] == ["1"]
    ledger.close()


def test_summary_resumed_dst_fold_retains_both_hours(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.sqlite3"))
    ledger.put_identity({"id": "i", "name": "Car"})
    ledger.put_point({"id": "p", "name": "Point"})
    start = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    parts = summary_parts(start, 1, energy="1", cost="-2")
    parts[0]["end"] = (start + timedelta(minutes=30)).isoformat()
    record = summary_record(
        ledger, "p", start, parts, active=True, timezone="America/New_York"
    )
    cache = {}
    queries.summarize(ledger, None, None, bucket_period="hour", cache=cache)
    tail = [
        {
            **parts[0],
            "start": parts[0]["end"],
            "end": (start + timedelta(minutes=90)).isoformat(),
        }
    ]
    record.update(
        revision=record["revision"] + 1,
        _segment_count=2,
        _accounted_until=tail[-1]["end"],
    )
    ledger.append_record_segments(record, tail, 1)
    cached = queries.summarize(ledger, None, None, bucket_period="hour", cache=cache)
    assert cached["energy_kwh"] == "2"
    assert [bucket["energy_kwh"] for bucket in cached["buckets"]] == ["1", "1"]
    assert [bucket["start"] for bucket in cached["buckets"]] == [
        "2026-11-01T05:00:00+00:00",
        "2026-11-01T06:00:00+00:00",
    ]
    assert cached == queries.summarize(ledger, None, None, bucket_period="hour")
    ledger.close()


def test_new_last_record_reuses_full_historical_checkpoint(tmp_path, monkeypatch):
    ledger = Ledger(str(tmp_path / "ledger.sqlite3"))
    ledger.put_identity({"id": "i", "name": "Car"})
    ledger.put_point({"id": "p", "name": "Point"})
    start = datetime(2026, 1, 1, tzinfo=UTC)
    old = summary_record(ledger, "p", start, summary_parts(start, 20_000))
    cache = {}
    queries.summarize(ledger, None, None, cache=cache)
    start += timedelta(days=1)
    new = summary_record(ledger, "p", start, summary_parts(start, 1), active=True)
    original = ledger.list_segments
    reads = []

    def observed(record_id, *, start_position=0):
        parts = original(record_id, start_position=start_position)
        reads.append((record_id, len(parts)))
        return parts

    monkeypatch.setattr(ledger, "list_segments", observed)
    cached = queries.summarize(ledger, None, None, cache=cache)
    assert reads == [(new["id"], 1)]
    assert old["id"] != new["id"]
    assert cached["energy_kwh"] == "20.001"
    assert cached["completed_count"] == 1
    assert cached == queries.summarize(ledger, None, None)
    ledger.close()


def test_noncontiguous_append_rebuilds_current_record(tmp_path, monkeypatch):
    ledger = Ledger(str(tmp_path / "ledger.sqlite3"))
    ledger.put_identity({"id": "i", "name": "Car"})
    ledger.put_point({"id": "p", "name": "Point"})
    start = datetime(2026, 1, 1, tzinfo=UTC)
    record = summary_record(ledger, "p", start, summary_parts(start, 1), active=True)
    cache = {}
    queries.summarize(ledger, None, None, cache=cache)
    tail = summary_parts(start + timedelta(seconds=2), 1, energy="7")
    record.update(
        revision=record["revision"] + 1,
        _segment_count=2,
        _accounted_until=tail[-1]["end"],
    )
    ledger.append_record_segments(record, tail, 1)
    original = ledger.list_segments
    positions = []

    def observed(record_id, *, start_position=0):
        positions.append(start_position)
        return original(record_id, start_position=start_position)

    monkeypatch.setattr(ledger, "list_segments", observed)
    cached = queries.summarize(ledger, None, None, cache=cache)
    assert positions == [1, 0]
    assert cached["energy_kwh"] == "7.001"
    assert cached["matched_count"] == cached["active_count"] == 1
    assert cached == queries.summarize(ledger, None, None)
    ledger.close()
