"""Repeated sample summaries reuse complete calendar windows."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.charge_tally import queries
from custom_components.charge_tally.accounting import Accounting
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
