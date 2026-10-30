"""Runtime tests exercise actual HA setup, events and SQLite persistence."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed_exact,
)

ENERGY = {
    "unit_of_measurement": "kWh",
    "device_class": "energy",
    "state_class": "total_increasing",
}
POWER = {
    "unit_of_measurement": "W",
    "device_class": "power",
    "state_class": "measurement",
}


async def setup_runtime(
    hass,
    tmp_path,
    *,
    detection=None,
    periods=None,
    mode="energy_power",
    price=None,
    timezone="Asia/Shanghai",
    extra_points=None,
):
    hass.config.config_dir = str(tmp_path)
    hass.config.time_zone = timezone
    hass.states.async_set("sensor.energy", "100", ENERGY)
    hass.states.async_set("sensor.power", "0", POWER)
    point = {
        "name": "Garage",
        "input_mode": mode,
        "energy_entity": "sensor.energy",
        "power_entity": "sensor.power",
        "resetting": True,
        "max_gap_seconds": 600,
        "periods": periods or [],
        "detection": detection or {"enabled": False},
        "price": price or {"mode": "static", "value": "2"},
    }
    entry = MockConfigEntry(
        domain="charge_tally",
        title="Charge Tally",
        data={"currency": "CNY"},
        subentries_data=[
            {
                "subentry_id": "car",
                "subentry_type": "identity",
                "title": "Car",
                "unique_id": None,
                "data": {"name": "Car", "enabled": True},
            },
            {
                "subentry_id": "point",
                "subentry_type": "point",
                "title": "Garage",
                "unique_id": None,
                "data": point,
            },
            *[
                {
                    "subentry_id": id_,
                    "subentry_type": "point",
                    "title": data["name"],
                    "unique_id": None,
                    "data": {**deepcopy(point), **data},
                }
                for id_, data in (extra_points or {}).items()
            ],
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hasattr(entry, "runtime_data"), "Root setup must create a real runtime"
    return entry, entry.runtime_data


async def test_live_system_timezone_change_preserves_active_evidence_and_new_record_zone(
    hass,
    tmp_path,
    freezer,
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await runtime.async_command(
        "select_identity", {"point_id": "point", "identity_id": "car"}
    )
    record = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "old-zone"}
    )
    await tick(hass, freezer, 5)
    hass.states.async_set("sensor.energy", "100.01", ENERGY)
    await hass.async_block_till_done()
    before = await runtime._worker(runtime._store.ledger.get_record, record["id"])
    parts = await runtime._worker(runtime._store.ledger.list_segments, record["id"])
    helpers = deepcopy(runtime._helper_results)
    observations = await runtime._worker(lambda: deepcopy(runtime._store.states))
    await hass.config.async_update(time_zone="UTC")
    await hass.async_block_till_done()
    assert runtime.snapshot["timezone"] == "UTC"
    assert (
        await runtime._worker(runtime._store.ledger.get_record, record["id"]) == before
    )
    assert (
        await runtime._worker(runtime._store.ledger.list_segments, record["id"])
        == parts
    )
    assert await runtime._worker(lambda: runtime._store.states) == observations
    assert runtime._helper_results == helpers
    assert runtime.snapshot["points"][0]["active_record"]["identity_id"] == "car"
    await runtime.async_command("end", {"record_id": record["id"], "request_id": "end"})
    await tick(hass, freezer, 1)
    new = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "new-zone"}
    )
    assert new["timezone"] == "UTC"
    assert new["identity_id"] == "car"
    assert await hass.config_entries.async_unload(entry.entry_id)
    revision = runtime.snapshot["revision"]
    await hass.config.async_update(time_zone="Europe/Berlin")
    await hass.async_block_till_done()
    assert runtime.snapshot["revision"] == revision


@pytest.mark.parametrize(
    "language, title",
    [
        ("en", "Charge Tally: Check time-of-use periods"),
        ("zh-Hans", "Charge Tally：请核对分时电价时段"),
        ("de", "Charge Tally: Zeitabhängige Tarifzeiten prüfen"),
        ("fr", "Charge Tally : Vérifiez les plages tarifaires"),
        ("pl", "Charge Tally: Sprawdź okresy taryfy czasowej"),
        ("it", "Charge Tally: Controlla le fasce orarie"),
    ],
)
async def test_tou_timezone_notification_is_native_consolidated_and_stays_dismissed(
    hass,
    tmp_path,
    hass_ws_client,
    language,
    title,
):
    from homeassistant.components import persistent_notification
    from homeassistant.helpers import issue_registry as ir
    from homeassistant.helpers.dispatcher import async_dispatcher_connect

    hass.config.language = language
    price = {
        "mode": "tou",
        "schedule": [{"start": "00:00", "end": "24:00", "price": "0.1"}],
    }
    hass.states.async_set("sensor.price", "0.2", {"unit_of_measurement": "CNY/kWh"})
    updates = []
    unsub = async_dispatcher_connect(
        hass,
        "persistent_notifications_updated",
        lambda kind, values: updates.append((kind, values)),
    )
    entry, runtime = await setup_runtime(
        hass,
        tmp_path,
        price=price,
        extra_points={
            "second": {"name": "Second TOU"},
            "static": {
                "name": "Static point",
                "price": {"mode": "static", "value": "1"},
            },
            "dynamic": {
                "name": "Dynamic point",
                "price": {
                    "mode": "dynamic",
                    "entity_id": "sensor.price",
                    "unit": "CNY/kWh",
                },
            },
        },
    )
    notification_id = "charge_tally_timezone_" + entry.entry_id
    assert not any(notification_id in values for _, values in updates)
    await hass.config.async_update(language="en" if language != "en" else "de")
    await hass.async_block_till_done()
    assert not any(notification_id in values for _, values in updates)
    hass.config.language = language
    await hass.config.async_update(time_zone="UTC")
    await hass.async_block_till_done()
    notices = [
        values[notification_id] for _, values in updates if notification_id in values
    ]
    assert len(notices) == 1
    assert notices[0]["title"] == title
    for text in ("Garage", "Second TOU", "Asia/Shanghai", "UTC"):
        assert text in notices[0]["message"]
    assert "Static point" not in notices[0]["message"]
    assert "Dynamic point" not in notices[0]["message"]
    assert not any(domain == "charge_tally" for domain, _ in ir.async_get(hass).issues)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "persistent_notification/get"})
    response = await client.receive_json()
    assert response["success"]
    assert (
        next(
            item
            for item in response["result"]
            if item["notification_id"] == notification_id
        )["title"]
        == title
    )
    persistent_notification.async_dismiss(hass, notification_id)
    await hass.async_block_till_done()
    updates.clear()
    await hass.config.async_update(time_zone="UTC")
    await runtime.async_refresh_config()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert not any(notification_id in values for _, values in updates)
    await client.send_json({"id": 2, "type": "persistent_notification/get"})
    assert all(
        item["notification_id"] != notification_id
        for item in (await client.receive_json())["result"]
    )
    unsub()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_live_tou_version_uses_core_event_instant_when_worker_is_paused(
    hass,
    tmp_path,
    freezer,
):
    freezer.move_to("2026-01-01T00:00:00Z")
    price = {
        "mode": "tou",
        "schedule": [
            {"start": "00:00", "end": "08:00", "price": "0.10"},
            {"start": "08:00", "end": "24:00", "price": "0.30"},
        ],
    }
    entry, runtime = await setup_runtime(hass, tmp_path, price=price, timezone="UTC")
    freezer.move_to("2026-01-01T01:00:00Z")
    runtime._gate.clear()
    await hass.config.async_update(time_zone="Asia/Shanghai")
    freezer.move_to("2026-01-01T01:01:00Z")
    runtime._gate.set()
    await hass.async_block_till_done()
    versions = await runtime._worker(runtime._store.ledger.list_price_versions, "point")
    assert len(versions) == 2
    assert versions[-1]["at"] == "2026-01-01T01:00:00+00:00"
    assert versions[-1]["timezone"] == "Asia/Shanghai"
    assert runtime.snapshot["points"][0]["current_price"] == "0.30"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_offline_tou_timezone_change_notifies_once_at_recognition(
    hass,
    tmp_path,
    freezer,
):
    from homeassistant.components import persistent_notification
    from homeassistant.helpers.dispatcher import async_dispatcher_connect

    updates = []
    unsub = async_dispatcher_connect(
        hass,
        "persistent_notifications_updated",
        lambda kind, values: updates.append(values),
    )
    freezer.move_to("2026-01-01T00:00:00Z")
    price = {
        "mode": "tou",
        "schedule": [{"start": "00:00", "end": "24:00", "price": "0.10"}],
    }
    entry, runtime = await setup_runtime(hass, tmp_path, price=price, timezone="UTC")
    original = await runtime._worker(runtime._store.ledger.list_price_versions, "point")
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.move_to("2026-01-01T01:00:00Z")
    await hass.config.async_update(time_zone="Asia/Shanghai")
    await hass.async_block_till_done()
    freezer.move_to("2026-01-01T02:00:00Z")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime = entry.runtime_data
    versions = await runtime._worker(runtime._store.ledger.list_price_versions, "point")
    assert versions[:-1] == original
    assert versions[-1]["at"] == "2026-01-01T02:00:00+00:00"
    notification_id = "charge_tally_timezone_" + entry.entry_id
    notices = [
        values[notification_id] for values in updates if notification_id in values
    ]
    assert len(notices) == 1
    message = notices[0]["message"]
    assert "Future time-of-use periods are interpreted in Asia/Shanghai" in message
    assert "Already-accounted fees remain unchanged" in message
    persistent_notification.async_dismiss(hass, notification_id)
    await hass.async_block_till_done()
    updates.clear()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert not any(notification_id in values for values in updates)
    unsub()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_failed_tou_timezone_commit_does_not_notify(hass, tmp_path, monkeypatch):
    from homeassistant.helpers.dispatcher import async_dispatcher_connect

    price = {
        "mode": "tou",
        "schedule": [{"start": "00:00", "end": "24:00", "price": "0.1"}],
    }
    entry, runtime = await setup_runtime(hass, tmp_path, price=price)
    before = deepcopy(runtime.snapshot)
    versions = await runtime._worker(runtime._store.ledger.list_price_versions, "point")
    notices = []
    unsub = async_dispatcher_connect(
        hass,
        "persistent_notifications_updated",
        lambda kind, values: notices.append(values),
    )
    snapshot = runtime._store.snapshot

    def fail_snapshot():
        raise OSError("Snapshot failed")

    monkeypatch.setattr(runtime._store, "snapshot", fail_snapshot)
    with pytest.raises(OSError, match="Snapshot failed"):
        await runtime._async_change_timezone("UTC", dt_util.utcnow())
    assert runtime.snapshot == before
    assert (
        await runtime._worker(runtime._store.ledger.list_price_versions, "point")
        == versions
    )
    assert notices == []
    monkeypatch.setattr(runtime._store, "snapshot", snapshot)
    unsub()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def tick(hass, freezer, seconds):
    freezer.move_to(dt_util.utcnow() + timedelta(seconds=seconds))
    async_fire_time_changed_exact(hass, dt_util.utcnow())
    await hass.async_block_till_done()


@pytest.mark.parametrize("backup_pending", [False, True])
@pytest.mark.parametrize("queued_refresh", [False, True])
async def test_close_waits_for_direct_config_refresh(
    hass, tmp_path, monkeypatch, backup_pending, queued_refresh
):
    entry, runtime = await setup_runtime(hass, tmp_path, mode="energy")
    helper_entered = asyncio.Event()
    release_helper = asyncio.Event()
    gate_waiting = asyncio.Event()
    close_started = asyncio.Event()
    release_queued = asyncio.Event()
    queued_waiting = asyncio.Event()
    ensure = runtime._helpers.async_ensure
    gate_wait = runtime._gate.wait
    gate_set = runtime._gate.set

    async def paused_ensure(*args, **kwargs):
        helper_entered.set()
        await release_helper.wait()
        return await ensure(*args, **kwargs)

    async def observed_gate_wait():
        if not runtime._gate.is_set():
            gate_waiting.set()
        await gate_wait()

    def observed_gate_set():
        gate_set()
        if runtime._closing:
            close_started.set()

    async def paused_queued_refresh():
        await release_queued.wait()
        queued_waiting.set()
        await runtime.async_refresh_config()

    monkeypatch.setattr(runtime._helpers, "async_ensure", paused_ensure)
    monkeypatch.setattr(runtime._gate, "wait", observed_gate_wait)
    monkeypatch.setattr(runtime._gate, "set", observed_gate_set)
    if backup_pending:
        await runtime.async_pre_backup()
    refresh = asyncio.create_task(runtime.async_refresh_config())
    closing = None
    try:
        await asyncio.wait_for(
            (gate_waiting if backup_pending else helper_entered).wait(), 5
        )
        assert runtime._config_lock.locked()
        # A queued refresh must also drain without close holding the config lock.
        if queued_refresh:
            runtime._queue(paused_queued_refresh())
        closing = asyncio.create_task(runtime.async_close())
        await asyncio.wait_for(close_started.wait(), 5)
        assert not runtime._closed
        if queued_refresh:
            release_queued.set()
            await asyncio.wait_for(queued_waiting.wait(), 5)
        if backup_pending:
            await asyncio.wait_for(helper_entered.wait(), 5)
        assert not runtime._closed
        assert not closing.done()
    finally:
        release_queued.set()
        release_helper.set()
        gate_set()
        tasks = [refresh] + ([closing] if closing is not None else [])
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), 5
        )
    assert results == [None, None]
    assert runtime._closed
    assert runtime._unsubs == []
    revision = runtime.snapshot["revision"]
    await asyncio.wait_for(runtime.async_refresh_config(), 5)
    assert runtime.snapshot["revision"] == revision
    assert runtime._unsubs == []
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_runtime_normalizes_shared_interval_and_reloads_without_duplicate(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(hass, tmp_path, periods=["daily"])
    initial = await runtime.async_snapshot()
    assert Decimal(initial["points"][0]["normalized_energy_kwh"]) == 0
    await runtime.async_command(
        "select_identity", {"point_id": "point", "identity_id": "car"}
    )
    record = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "start1"}
    )
    await tick(hass, freezer, 30)
    hass.states.async_set("sensor.energy", "100.060", ENERGY)
    await hass.async_block_till_done()
    point = (await runtime.async_snapshot())["points"][0]
    assert Decimal(point["normalized_energy_kwh"]) == Decimal(".060")
    assert Decimal(point["active_record"]["energy_kwh"]) == Decimal(".060")
    assert Decimal(point["active_record"]["known_cost"]) == Decimal(".120")
    await runtime.async_command(
        "select_identity", {"point_id": "point", "identity_id": "unassigned"}
    )
    assert (await runtime.async_snapshot())["points"][0]["active_record"][
        "identity_id"
    ] == "car"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    point = (await entry.runtime_data.async_snapshot())["points"][0]
    assert Decimal(point["normalized_energy_kwh"]) == Decimal(".060")
    assert point["active_record"]["id"] == record["id"]
    assert point["active_record"]["identity_id"] == "car"
    assert not await entry.runtime_data.async_config_guard("point", {}, {})
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_timer_confirms_unchanged_power_with_latest_candidate_identity(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(
        hass,
        tmp_path,
        detection={
            "enabled": True,
            "start_w": "500",
            "end_w": "100",
            "start_seconds": 30,
            "end_seconds": 60,
        },
    )
    await runtime.async_command(
        "select_identity", {"point_id": "point", "identity_id": "car"}
    )
    hass.states.async_set("sensor.power", "1000", POWER)
    await hass.async_block_till_done()
    candidate = (await runtime.async_snapshot())["points"][0]
    assert candidate["status"] == "pending_start"
    assert candidate["candidate_identity_id"] == "car"
    assert not await runtime.async_config_guard("point", {}, {})
    await tick(hass, freezer, 10)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": candidate["identity_entity_id"], "option": "Unassigned"},
        blocking=True,
    )
    selected = (await runtime.async_snapshot())["points"][0]
    assert selected["selected_identity_id"] == "unassigned"
    assert selected["candidate_identity_id"] == "unassigned"
    assert selected["candidate"] == candidate["candidate"]
    await tick(hass, freezer, 21)
    point = (await runtime.async_snapshot())["points"][0]
    assert point["status"] == "charging"
    assert point["active_record"]["identity_id"] == "unassigned"
    assert point["active_record"]["start"] == candidate["candidate"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_repeated_meter_reports_refresh_coverage_and_invalid_price_ends_rate(
    hass, tmp_path, freezer
):
    hass.states.async_set("sensor.price", "2", {"unit_of_measurement": "CNY/kWh"})
    entry, runtime = await setup_runtime(
        hass,
        tmp_path,
        price={"mode": "dynamic", "entity_id": "sensor.price", "unit": "CNY/kWh"},
    )
    await runtime.async_command("start", {"point_id": "point", "request_id": "r1"})
    for _ in range(3):
        await tick(hass, freezer, 300)
        hass.states.async_set("sensor.energy", "100", ENERGY)
        await hass.async_block_till_done()
    hass.states.async_set(
        "sensor.price", "unavailable", {"unit_of_measurement": "CNY/kWh"}
    )
    await hass.async_block_till_done()
    await tick(hass, freezer, 60)
    hass.states.async_set("sensor.energy", "100.060", ENERGY)
    await hass.async_block_till_done()
    point = (await runtime.async_snapshot())["points"][0]
    assert Decimal(point["active_record"]["energy_kwh"]) == Decimal(".060")
    assert point["current_price"] is None
    assert point["active_record"]["cost_complete"] is False
    assert "missing_energy" not in point["active_record"]["quality"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_unconfigured_switch_refuses_invented_thresholds(hass, tmp_path):
    entry, runtime = await setup_runtime(hass, tmp_path)
    with pytest.raises(ValueError, match="[Cc]onfigur"):
        await runtime.async_command(
            "set_detection", {"point_id": "point", "enabled": True}
        )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_tariff_config_change_splits_interval_and_keeps_versions(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await runtime.async_command("start", {"point_id": "point", "request_id": "r1"})
    await tick(hass, freezer, 15)
    sub = entry.subentries["point"]
    hass.config_entries.async_update_subentry(
        entry, sub, data={**sub.data, "price": {"mode": "static", "value": "-1"}}
    )
    await hass.async_block_till_done()
    await tick(hass, freezer, 15)
    hass.states.async_set("sensor.energy", "100.060", ENERGY)
    await hass.async_block_till_done()
    record = (await runtime.async_snapshot())["records"][0]
    assert Decimal(record["energy_kwh"]) == Decimal(".060")
    assert Decimal(record["known_cost"]) == Decimal(".030")
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_long_valid_meter_interval_is_allocated_as_estimated(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await runtime.async_command("start", {"point_id": "point", "request_id": "r1"})
    await tick(hass, freezer, 601)
    hass.states.async_set("sensor.energy", "101", ENERGY)
    await hass.async_block_till_done()
    point = (await runtime.async_snapshot())["points"][0]
    assert Decimal(point["normalized_energy_kwh"]) == 1
    assert Decimal(point["active_record"]["energy_kwh"]) == 1
    assert Decimal(point["active_record"]["known_cost"]) == 2
    assert point["active_record"]["cost_complete"]
    assert "estimated" in point["active_record"]["quality"]
    assert "missing_energy" not in point["active_record"]["quality"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_retry_uses_original_identity_and_time_after_selection_changes(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    payload = {"point_id": "point", "request_id": "r1"}
    original = await runtime.async_command("start", payload)
    await runtime.async_command(
        "select_identity", {"point_id": "point", "identity_id": "car"}
    )
    await tick(hass, freezer, 10)
    assert await runtime.async_command("start", payload) == original
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_power_only_runtime_uses_native_integral_then_utility_meter(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(
        hass, tmp_path, mode="power", periods=["daily"]
    )
    assert len(hass.config_entries.async_entries("integration")) == 1
    assert len(hass.config_entries.async_entries("utility_meter")) == 1
    hass.states.async_set("sensor.power", "1000", POWER)
    await hass.async_block_till_done()
    await tick(hass, freezer, 60)
    point = (await runtime.async_snapshot())["points"][0]
    # Drain published source-state callbacks before checking the native meter.
    await hass.async_block_till_done()
    assert abs(Decimal(point["normalized_energy_kwh"]) - Decimal(".016667")) < Decimal(
        ".000002"
    )
    assert abs(
        Decimal(hass.states.get(point["utility_entities"]["daily"]).state)
        - Decimal(".016667")
    ) < Decimal(".000002")
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_midnight_refresh_changes_identity_period_without_new_meter_read(
    hass, tmp_path, freezer
):
    freezer.move_to("2026-09-10T15:59:00+00:00")
    entry, runtime = await setup_runtime(hass, tmp_path)
    await runtime.async_command(
        "start", {"point_id": "point", "identity_id": "car", "request_id": "r1"}
    )
    await tick(hass, freezer, 30)
    hass.states.async_set("sensor.energy", "101", ENERGY)
    await hass.async_block_till_done()
    identity = next(
        i for i in (await runtime.async_snapshot())["identities"] if i["id"] == "car"
    )
    assert Decimal(identity["summaries"]["daily"]["energy_kwh"]) == 1
    await tick(hass, freezer, 31)
    identity = next(
        i for i in (await runtime.async_snapshot())["identities"] if i["id"] == "car"
    )
    assert Decimal(identity["summaries"]["daily"]["energy_kwh"]) == 0
    assert Decimal(identity["summaries"]["total"]["energy_kwh"]) == 1
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_manual_record_with_configured_detector_stays_charging_and_cannot_void(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(
        hass,
        tmp_path,
        detection={
            "enabled": True,
            "start_w": "500",
            "end_w": "100",
            "start_seconds": 30,
            "end_seconds": 60,
        },
    )
    record = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "r1"}
    )
    await tick(hass, freezer, 120)
    point = (await runtime.async_snapshot())["points"][0]
    assert point["status"] == "charging"
    assert point["active_record"]["id"] == record["id"]
    with pytest.raises(ValueError, match="[Ee]nd"):
        await runtime.async_command(
            "void", {"record_id": record["id"], "expected_revision": record["revision"]}
        )
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("mode", ["energy", "energy_power", "power"])
async def test_unavailable_source_immediately_prevents_manual_start(
    hass, tmp_path, mode
):
    entry, runtime = await setup_runtime(hass, tmp_path, mode=mode)
    source, attrs = (
        ("sensor.power", POWER) if mode == "power" else ("sensor.energy", ENERGY)
    )
    hass.states.async_set(source, "unavailable", attrs)
    with pytest.raises(ValueError):
        await runtime.async_command("start", {"point_id": "point", "request_id": "r1"})
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("public", [False, True])
async def test_source_unavailable_rejects_new_start_but_preserves_completed_request_replay(
    hass, tmp_path, public
):
    entry, runtime = await setup_runtime(hass, tmp_path)

    async def start(request_id):
        payload = {"point_id": "point", "request_id": request_id}
        if public:
            return await runtime.async_public_command(
                "start", payload, "test-user", lambda: None
            )
        return await runtime.async_command("start", payload)

    first = await start("original")
    hass.states.async_set("sensor.energy", "unavailable", ENERGY)
    assert await start("original") == first
    with pytest.raises(ValueError, match="valid measurement baseline"):
        await start("new-intent")
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_automatic_end_backdates_record_without_reducing_normalized_energy(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(
        hass,
        tmp_path,
        detection={
            "enabled": True,
            "start_w": "500",
            "end_w": "100",
            "start_seconds": 30,
            "end_seconds": 60,
        },
    )
    hass.states.async_set("sensor.power", "1000", POWER)
    await hass.async_block_till_done()
    await tick(hass, freezer, 31)
    await tick(hass, freezer, 29)
    hass.states.async_set("sensor.energy", "100.060", ENERGY)
    hass.states.async_set("sensor.power", "0", POWER)
    await hass.async_block_till_done()
    assert (await runtime.async_snapshot())["points"][0]["status"] == "pending_end"
    await tick(hass, freezer, 30)
    hass.states.async_set("sensor.energy", "100.090", ENERGY)
    await hass.async_block_till_done()
    assert Decimal(
        (await runtime.async_snapshot())["records"][0]["energy_kwh"]
    ) == Decimal(".090")
    await tick(hass, freezer, 31)
    snapshot = await runtime.async_snapshot()
    assert snapshot["records"][0]["status"] == "ended"
    assert Decimal(snapshot["records"][0]["energy_kwh"]) == Decimal(".060")
    assert Decimal(snapshot["points"][0]["normalized_energy_kwh"]) == Decimal(".090")
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_snapshot_failure_rolls_back_without_publication_and_next_reading_recovers(
    hass, tmp_path, freezer, monkeypatch
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await runtime.async_command("start", {"point_id": "point", "request_id": "r1"})
    before = await runtime.async_snapshot()
    start = dt_util.utcnow()

    def fail_snapshot(*args):
        raise OSError("snapshot read failed")

    with monkeypatch.context() as scoped:
        scoped.setattr(runtime._store, "snapshot", fail_snapshot)
        with pytest.raises(OSError, match="snapshot read"):
            await runtime._apply(
                "energy", "point", start + timedelta(seconds=30), Decimal("100.060")
            )
    assert await runtime.async_snapshot() == before
    checkpoint = await runtime._read(runtime._store.ledger.get_checkpoint, "runtime")
    assert Decimal(checkpoint["point"]["normalized_energy_kwh"]) == 0
    await runtime._apply(
        "energy", "point", start + timedelta(seconds=60), Decimal("100.070")
    )
    snapshot = await runtime.async_snapshot()
    assert Decimal(snapshot["points"][0]["normalized_energy_kwh"]) == Decimal(".070")
    assert Decimal(snapshot["records"][0]["energy_kwh"]) == Decimal(".070")
    intervals = await runtime._read(runtime._store.ledger.list_intervals, "point")
    assert len(intervals) == 1
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("live_power", ["1000", "unavailable"])
async def test_end_checks_live_power_before_queued_change(
    hass, tmp_path, freezer, live_power, monkeypatch, public
):
    entry, runtime = await setup_runtime(
        hass,
        tmp_path,
        detection={
            "enabled": True,
            "start_w": "500",
            "end_w": "100",
            "start_seconds": 30,
            "end_seconds": 60,
        },
    )
    record = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "manual"}
    )
    await tick(hass, freezer, 1)
    hass.states.async_set("sensor.power", "0", POWER, force_update=True)
    await hass.async_block_till_done()
    await tick(hass, freezer, 1)
    release = asyncio.Event()
    handle = runtime._handle_observation

    async def delayed(point_id, role, data):
        if role == "power":
            await release.wait()
        await handle(point_id, role, data)

    monkeypatch.setattr(runtime, "_handle_observation", delayed)
    hass.states.async_set("sensor.power", live_power, POWER)
    try:
        payload = {"record_id": record["id"], "request_id": "end"}
        if public:
            await runtime.async_public_command(
                "end",
                {
                    **payload,
                    "point_id": "point",
                    "expected_revision": record["revision"],
                },
                "admin",
                lambda: None,
            )
        else:
            await runtime.async_command("end", payload)
        blocked = runtime.snapshot["points"][0]["detection_state"]
    finally:
        release.set()
    await hass.async_block_till_done()
    assert blocked == "blocked"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_manual_takeover_cancels_timer_then_low_end_allows_next_cycle(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(
        hass,
        tmp_path,
        detection={
            "enabled": True,
            "start_w": "500",
            "end_w": "100",
            "start_seconds": 30,
            "end_seconds": 60,
        },
    )
    hass.states.async_set("sensor.power", "1000", POWER)
    await hass.async_block_till_done()
    assert "point" in runtime._timers
    record = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "manual"}
    )
    assert runtime._timers == {}
    await tick(hass, freezer, 31)
    assert runtime.snapshot["points"][0]["active_record"]["source"] == "manual"
    hass.states.async_set("sensor.power", "0", POWER)
    await hass.async_block_till_done()
    await tick(hass, freezer, 1)
    await runtime.async_command("end", {"record_id": record["id"], "request_id": "end"})
    assert runtime.snapshot["points"][0]["detection_state"] == "waiting"
    hass.states.async_set("sensor.power", "1000", POWER)
    await hass.async_block_till_done()
    await tick(hass, freezer, 31)
    assert runtime.snapshot["points"][0]["active_record"]["source"] == "automatic"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_initial_observations_do_not_refresh_old_low_evidence(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(
        hass,
        tmp_path,
        detection={
            "enabled": True,
            "start_w": "500",
            "end_w": "100",
            "start_seconds": 30,
            "end_seconds": 60,
        },
    )
    record = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "manual"}
    )
    await tick(hass, freezer, 1)
    hass.states.async_set("sensor.power", "0", POWER, force_update=True)
    await hass.async_block_till_done()
    await tick(hass, freezer, 601)
    await runtime._initial_observations({("point", "power")})
    await runtime.async_command("end", {"record_id": record["id"], "request_id": "end"})
    assert runtime.snapshot["points"][0]["detection_state"] == "blocked"
    assert await hass.config_entries.async_unload(entry.entry_id)
