"""Exercise bounded dashboard work without wall-clock timing assertions."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from homeassistant.helpers.dispatcher import async_dispatcher_send
from test_runtime import setup_runtime
from test_runtime_store import configured, save_report_record


def test_snapshots_and_queries_reuse_unchanged_statistics(tmp_path):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    store, _ = configured(tmp_path, at)
    save_report_record(store)
    store.snapshot()
    statements = []
    store.ledger._db.set_trace_callback(statements.append)
    snapshot = store.snapshot(["p"])
    summary = store.query("summary", {"calendar_period": "total"}, ["p"])
    assert Decimal(summary["energy_kwh"]) == 1
    snapshot["identities"][0]["summaries"]["total"]["energy_kwh"] = "999"
    assert Decimal(store.snapshot(["p"])["summary"]["energy_kwh"]) == 1
    assert not any("SELECT data FROM segments" in sql for sql in statements)
    store.ledger.close()


def test_power_observation_updates_live_value_without_rescanning_segments(tmp_path):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    store, _ = configured(tmp_path, at)
    save_report_record(store)
    store.snapshot()
    statements = []
    store.ledger._db.set_trace_callback(statements.append)
    _, snapshot = store.apply(
        "observe", "p", "power", {"at": at.isoformat(), "value": "123", "unit": "W"}
    )
    assert snapshot["points"][0]["power_w"] == "123"
    assert Decimal(snapshot["summary"]["energy_kwh"]) == 1
    assert not any("SELECT data FROM segments" in sql for sql in statements)
    store.ledger.close()


def test_summary_cache_keeps_scope_calendar_and_edits_separate(tmp_path, freezer):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    freezer.move_to(at + timedelta(hours=1))
    store, point = configured(tmp_path, at)
    store.configure({"p": point, "other": point}, {"i": {"name": "Car"}}, at, "UTC")
    record = save_report_record(store)
    save_report_record(store, point_id="other", energy="7", request="other")
    query = {"calendar_period": "daily"}
    assert Decimal(store.query("summary", query, ["p"])["energy_kwh"]) == 1
    assert Decimal(store.query("summary", query, ["other"])["energy_kwh"]) == 7
    assert Decimal(store.query("summary", query, [])["energy_kwh"]) == 0
    freezer.move_to(at + timedelta(days=1))
    assert Decimal(store.query("summary", query, ["p"])["energy_kwh"]) == 0
    assert Decimal(store.query("summary", {}, ["p"])["energy_kwh"]) == 1
    store.accounting.void(record["id"], record["revision"])
    assert Decimal(store.query("summary", {}, ["p"])["energy_kwh"]) == 0
    store.ledger.close()


def test_rolled_back_summary_is_not_reused_by_next_measurement(tmp_path, monkeypatch):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    store, _ = configured(tmp_path, at)
    store.apply("energy", "p", at, Decimal(100))
    store.apply("command", "start", {"point_id": "p", "request_id": "start"}, at)
    store.apply("energy", "p", at + timedelta(seconds=5), Decimal(101))
    snapshot = store.snapshot

    def fail_after_summary(*args):
        snapshot(*args)
        raise OSError("Injected snapshot failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(store, "snapshot", fail_after_summary)
        with pytest.raises(OSError, match="Injected"):
            store.apply("energy", "p", at + timedelta(seconds=10), Decimal(102))
    _, result = store.apply("energy", "p", at + timedelta(seconds=10), Decimal(103))
    assert Decimal(result["summary"]["energy_kwh"]) == 3
    store.ledger.close()


async def test_all_point_clients_read_the_published_snapshot(
    hass, tmp_path, monkeypatch
):
    entry, runtime = await setup_runtime(hass, tmp_path)

    def unavailable_worker(*args):
        raise AssertionError("A published full snapshot must not queue a ledger read")

    monkeypatch.setattr(runtime._store, "snapshot", unavailable_worker)
    snapshots = await asyncio.gather(
        *(runtime.async_snapshot(["point"]) for _ in range(3))
    )
    assert all(item["points"][0]["id"] == "point" for item in snapshots)
    snapshots[0]["points"][0]["name"] = "Changed by caller"
    assert snapshots[1]["points"][0]["name"] == "Garage"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_subscription_coalesces_updates_while_snapshot_is_pending(
    hass, tmp_path, hass_ws_client, monkeypatch
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "charge_tally/subscribe"})
    assert (await client.receive_json())["success"]
    await client.receive_json()
    entered, release = asyncio.Event(), asyncio.Event()
    snapshot = runtime.async_snapshot
    calls = 0

    async def slow_snapshot(*args):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return await snapshot(*args)

    monkeypatch.setattr(runtime, "async_snapshot", slow_snapshot)
    async_dispatcher_send(hass, runtime.update_signal)
    await entered.wait()
    for _ in range(20):
        async_dispatcher_send(hass, runtime.update_signal)
    await asyncio.sleep(0)
    pending_calls = calls
    release.set()
    await hass.async_block_till_done()
    assert pending_calls == 1
    assert calls <= 2
    await client.send_json({"id": 2, "type": "unsubscribe_events", "subscription": 1})
    assert (await client.receive_json())["success"]
    await hass.config_entries.async_unload(entry.entry_id)


def test_record_page_decodes_only_authorized_page_rows(tmp_path, monkeypatch):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    store, point = configured(tmp_path, at)
    store.configure({"p": point, "other": point}, {"i": {"name": "Car"}}, at, "UTC")
    records = [
        save_report_record(
            store,
            point_id="p" if index % 2 == 0 else "other",
            start=at + timedelta(hours=index),
            end=at + timedelta(hours=index, minutes=1),
            request=str(index),
        )
        for index in range(20)
    ]
    loads = json.loads
    decoded = []

    def observed_loads(value, *args, **kwargs):
        result = loads(value, *args, **kwargs)
        if isinstance(result, dict) and "revision" in result and "point_id" in result:
            decoded.append(result["id"])
        return result

    monkeypatch.setattr(
        "custom_components.charge_tally.ledger.json.loads", observed_loads
    )
    page = store.query("records", {"offset": 2, "limit": 3}, ["p"])
    assert page["total"] == 10
    assert [record["id"] for record in page["records"]] == [
        records[index]["id"] for index in (14, 12, 10)
    ]
    assert len(decoded) == 3
    assert store.query("records", {"limit": 3}, [])["total"] == 0
    # Equivalent non-UTC bounds keep the existing strict overlap semantics.
    page = store.query(
        "records",
        {"start": "2026-01-01T10:01:00+02:00", "end": "2026-01-01T14:00:00+02:00"},
        ["p"],
    )
    assert page["total"] == 1
    assert page["records"][0]["id"] == records[10]["id"]
    store.ledger.close()
