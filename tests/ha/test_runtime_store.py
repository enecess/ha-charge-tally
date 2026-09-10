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


@pytest.mark.parametrize("name", ["Unassigned", " unASSIGNED "])
def test_reserved_identity_config_is_atomic(tmp_path, name):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    store, point = configured(tmp_path, at)
    before = store.snapshot()
    with pytest.raises(ValueError, match="duplicate_name"):
        store.apply("configure", {"p": point}, {"i": {"name": name, "enabled": True}}, at, "UTC")
    assert store.snapshot() == before
    store.ledger.close()


@pytest.mark.parametrize("cost", ["automatic", "7", None])
def test_manual_preview_recorder_price_recovery_invalidates_only_automatic(tmp_path, cost):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    end = at + timedelta(minutes=5)
    store, point = configured(tmp_path, at, {"mode": "dynamic", "entity_id": "sensor.price", "unit": "CNY/kWh"})
    data = {"point_id": "p", "identity_id": "i", "start": at.isoformat(), "end": end.isoformat(), "energy_kwh": "10"}
    if cost != "automatic":
        data["cost"] = cost
    old, _ = store.apply("command", "preview", data, end)
    store.apply("import_history", "p", [{"start": at.isoformat(), "end": end.isoformat(), "energy_kwh": "10", "quality": []}], [(at, Decimal("2"))])
    fresh, _ = store.apply("command", "preview", data, end)
    if cost == "automatic":
        assert Decimal(fresh["record"]["known_cost"]) == 20
        with pytest.raises(ValueError, match="stale"):
            store.apply("command", "commit_preview", {"token": old["token"], "request_id": "old"}, end)
    else:
        saved, _ = store.apply("command", "commit_preview", {"token": old["token"], "request_id": "old"}, end)
        assert saved["manual_cost"] == cost
    store.ledger.close()


def test_manual_preview_price_versions_respect_effective_range(tmp_path):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    end = at + timedelta(hours=2)
    tou = {"mode": "tou", "schedule": [{"start": "00:00", "end": "01:00", "price": "1"}, {"start": "01:00", "end": "24:00", "price": "2"}]}
    store, point = configured(tmp_path, at, tou)
    data = {"point_id": "p", "identity_id": "i", "start": at.isoformat(), "end": end.isoformat(), "energy_kwh": "10"}
    old, _ = store.apply("command", "preview", data, end)
    assert Decimal(old["record"]["known_cost"]) == 15
    store.apply("put_price", {"point_id": "p", "at": end.isoformat(), "mode": "dynamic", "price": "99"})
    fresh, _ = store.apply("command", "preview", data, end)
    assert old["basis_fingerprint"] == fresh["basis_fingerprint"]
    store.apply("put_price", {"point_id": "p", "at": (at + timedelta(hours=1)).isoformat(), "mode": "dynamic", "price": "3"})
    with pytest.raises(ValueError, match="stale"):
        store.apply("command", "commit_preview", {"token": old["token"], "request_id": "old"}, end)
    fresh, _ = store.apply("command", "preview", data, end)
    assert Decimal(fresh["record"]["known_cost"]) == 20
    store.ledger.close()



def test_ledger_currency_survives_recreation_and_rejects_relabel(tmp_path):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    store, point = configured(tmp_path, at)
    data = {"point_id": "p", "identity_id": "i", "start": at.isoformat(), "end": (at + timedelta(minutes=5)).isoformat(), "energy_kwh": "10", "cost": "10"}
    preview, _ = store.apply("command", "preview", data, at)
    store.apply("command", "commit_preview", {"token": preview["token"], "request_id": "save"}, at)
    records = store.ledger.list_records()
    store.ledger.close()
    path = str(tmp_path / "ledger.sqlite3")
    with pytest.raises(ValueError, match="currency_mismatch"):
        RuntimeStore(path, "USD", "UTC")
    reopened = RuntimeStore(path, "CNY", "UTC")
    assert reopened.ledger.list_records() == records
    assert reopened.ledger.currency == "CNY"
    reopened.ledger.close()


def test_unbound_pre_release_ledger_requires_explicit_currency_confirmation(tmp_path):
    from custom_components.charge_tally.ledger import Ledger
    path = str(tmp_path / "ledger.sqlite3")
    ledger = Ledger(path)
    ledger.put_point({"id": "p", "name": "Old point"})
    ledger.put_price_version({"id": "old", "point_id": "p", "at": "2026-01-01T00:00:00Z", "price": "2"})
    prices = ledger.list_price_versions("p")
    ledger.close()
    with pytest.raises(ValueError, match="currency_unbound"):
        RuntimeStore(path, "USD", "UTC")
    ledger = Ledger(path)
    ledger.backup(str(tmp_path / "before.sqlite3"))
    ledger.bind_currency("CNY", confirm_existing=True)
    assert ledger.list_price_versions("p") == prices
    ledger.close()
    restored = RuntimeStore(path, "CNY", "UTC")
    assert restored.ledger.currency == "CNY"
    restored.ledger.close()


@pytest.mark.parametrize("start,end,now,zone,energy", [
    ("2026-01-01T00:00:00+08:00", "2026-01-01T01:00:00+08:00", "2026-01-01T12:00:00Z", "Asia/Shanghai", "10"),
    ("2026-02-01T00:00:00+08:00", "2026-02-01T01:00:00+08:00", "2026-02-01T12:00:00Z", "Asia/Shanghai", "10"),
    ("2025-11-02T00:00:00-04:00", "2025-11-03T00:00:00-05:00", "2025-11-02T12:00:00Z", "America/New_York", "25"),
    ("2026-03-08T00:00:00-05:00", "2026-03-09T00:00:00-04:00", "2026-03-08T12:00:00Z", "America/New_York", "23"),
])
def test_calendar_summary_preserves_original_timezone(tmp_path, monkeypatch, start, end, now, zone, energy):
    fixed = datetime.fromisoformat(now)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
    store, point = configured(tmp_path, datetime(2025, 1, 1, tzinfo=UTC))
    store.apply("configure", {"p": point}, {"i": {"name": "Car", "enabled": True}}, fixed, zone)
    preview, _ = store.apply("command", "preview", {"point_id": "p", "identity_id": "i", "start": start, "end": end, "energy_kwh": energy, "cost": energy}, fixed)
    store.apply("command", "commit_preview", {"token": preview["token"], "request_id": "save"}, fixed)
    monkeypatch.setattr("custom_components.charge_tally.runtime_store.datetime", Clock)
    store.apply("configure", {"p": point}, {"i": {"name": "Car", "enabled": True}}, fixed, "UTC")
    identity = next(i for i in store.snapshot()["identities"] if i["id"] == "i")
    for period in ("daily", "monthly", "yearly"):
        result = store.query("summary", {"calendar_period": period, "identity_id": "i"}, ["p"])
        assert Decimal(result["energy_kwh"]) == Decimal(energy)
        assert result["completed_count"] == 1
        assert result == identity["summaries"][period]
    store.ledger.close()


@pytest.mark.parametrize("cost", ["automatic", "7", None])
def test_preview_ignores_other_point_and_future_configuration_prices(tmp_path, cost):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    end = at + timedelta(minutes=5)
    store, point = configured(tmp_path, at)
    data = {"point_id": "p", "identity_id": "i", "start": at.isoformat(), "end": end.isoformat(), "energy_kwh": "10"}
    if cost != "automatic":
        data["cost"] = cost
    old, _ = store.apply("command", "preview", data, end)
    store.apply("configure", {"p": {**point, "price": {"mode": "static", "value": "99"}}, "other": point}, {"i": {"name": "Car", "enabled": True}}, end, "UTC")
    store.apply("put_price", {"point_id": "other", "at": at.isoformat(), "mode": "dynamic", "price": "123"})
    saved, _ = store.apply("command", "commit_preview", {"token": old["token"], "request_id": "save"}, end)
    assert saved["known_cost"] == old["record"]["known_cost"]
    store.ledger.close()
