"""Runtime worker invariants use actual SQLite and explicit fault injection."""
from datetime import datetime, UTC, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from custom_components.charge_tally.runtime_store import RuntimeStore


def configured(tmp_path, at, price=None):
    store = RuntimeStore(str(tmp_path / "ledger.sqlite3"), "CNY", "UTC")
    point = {"name": "Point", "input_mode": "energy", "energy_entity": "sensor.a", "detection": {"enabled": False},
             "price": price or {"mode": "static", "value": "2"}, "periods": [], "resetting": True, "max_gap_seconds": 600}
    store.apply("configure", {"p": point}, {"i": {"name": "Car", "enabled": True}}, at, "UTC")
    return store, point


def test_transaction_failure_rolls_back_increment_record_and_checkpoint(tmp_path, monkeypatch):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    store, _ = configured(tmp_path, at)
    store.apply("energy", "p", at, Decimal("100"))
    store.apply("command", "start", {"point_id": "p", "request_id": "r1"}, at)
    original = store.ledger.put_checkpoint
    def fail(key, data):
        if key == "runtime":
            raise OSError("disk write failed")
        return original(key, data)
    with monkeypatch.context() as scoped:
        scoped.setattr(store.ledger, "put_checkpoint", fail)
        with pytest.raises(OSError):
            store.apply("energy", "p", at + timedelta(seconds=30), Decimal("100.060"))
    assert store.states["p"]["normalized_energy_kwh"] == "0"
    assert store.ledger.list_intervals("p") == []
    assert Decimal(store.ledger.list_records()[0]["energy_kwh"]) == 0
    store.apply("energy", "p", at + timedelta(seconds=30), Decimal("100.060"))
    assert Decimal(store.ledger.list_records()[0]["energy_kwh"]) == Decimal(".060")
    store.ledger.close()


def test_changed_source_does_not_import_new_entity_before_input_epoch(tmp_path):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    store, point = configured(tmp_path, at)
    store.apply("configure", {"p": {**point, "energy_entity": "sensor.b"}}, {}, at + timedelta(hours=1), "UTC")
    interval = {"start": at.isoformat(), "end": (at + timedelta(seconds=30)).isoformat(), "energy_kwh": "5", "quality": [], "gap": False}
    store.apply("import_history", "p", [interval])
    assert store.ledger.list_intervals("p") == []
    store.apply("observe", "p", "energy", {"entity_id": "sensor.a", "at": (at + timedelta(hours=1)).isoformat(),
        "value": "500", "unit": "kWh", "state_class": "total_increasing"})
    assert store.states["p"]["reading"] is None
    store.ledger.close()


def test_pruned_tou_price_is_unknown_even_across_daily_schedule_boundary(tmp_path):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    tou = {"mode": "tou", "schedule": [{"start": "00:00", "end": "12:00", "price": "1"}, {"start": "12:00", "end": "24:00", "price": "2"}]}
    store, _ = configured(tmp_path, at, tou)
    record = store.accounting.start("p", "i", at, "first")
    store.accounting.end(record["id"], at + timedelta(hours=1), "last")
    for index in (1, 2):
        store.ledger.put_price_version({"id": str(index), "point_id": "p", "at": (at + timedelta(days=index)).isoformat(), "mode": "static", "price": str(index + 3)})
    store.ledger.prune(before=at + timedelta(days=2, hours=1))
    # The removed middle interval cannot inherit a retained daily schedule.
    timeline = store.prices("p", at + timedelta(days=1, hours=11), at + timedelta(days=1, hours=13))
    assert all(value is None for _, value in timeline)
    store.ledger.close()


def test_same_timestamp_dynamic_observation_overrides_configuration_unknown(tmp_path, monkeypatch):
    import custom_components.charge_tally.runtime_store as runtime_store
    ids = iter([UUID(int=2**128 - 1), UUID(int=0)])
    monkeypatch.setattr(runtime_store, "uuid4", lambda: next(ids))
    at = datetime(2026, 1, 1, tzinfo=UTC)
    store, _ = configured(tmp_path, at, {"mode": "dynamic", "entity_id": "sensor.price", "unit": "CNY/kWh"})
    store.apply("observe", "p", "price", {"entity_id": "sensor.price", "at": at.isoformat(), "value": "2", "unit": "CNY/kWh"})
    assert store.prices("p", at, at + timedelta(seconds=30))[0][1] == Decimal("2")
    store.ledger.close()


def test_same_timestamp_energy_change_is_deferred_not_lost(tmp_path):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    store, _ = configured(tmp_path, at)
    store.apply("energy", "p", at, Decimal("100"))
    store.apply("energy", "p", at, Decimal("100.060"))
    store.apply("energy", "p", at + timedelta(seconds=30), Decimal("100.070"))
    assert Decimal(store.states["p"]["normalized_energy_kwh"]) == Decimal(".070")
    store.ledger.close()
