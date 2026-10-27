"""Runtime tests exercise actual HA setup, events and SQLite persistence."""

import asyncio
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
    hass, tmp_path, *, detection=None, periods=None, mode="energy_power", price=None
):
    hass.config.config_dir = str(tmp_path)
    hass.config.time_zone = "Asia/Shanghai"
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
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hasattr(entry, "runtime_data"), "Root setup must create a real runtime"
    return entry, entry.runtime_data


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


async def test_long_gap_preserves_total_but_not_record_allocation(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await runtime.async_command("start", {"point_id": "point", "request_id": "r1"})
    await tick(hass, freezer, 601)
    hass.states.async_set("sensor.energy", "101", ENERGY)
    await hass.async_block_till_done()
    point = (await runtime.async_snapshot())["points"][0]
    assert Decimal(point["normalized_energy_kwh"]) == 1
    assert Decimal(point["active_record"]["energy_kwh"]) == 0
    assert "missing_energy" in point["active_record"]["quality"]
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
