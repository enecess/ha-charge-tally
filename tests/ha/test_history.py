"""Recorder adapter reads recorded cumulative energy, never raw power integration."""
from datetime import timedelta
from decimal import Decimal

import pytest

from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done, async_wait_recorder

from test_runtime import ENERGY, POWER, setup_runtime, tick


@pytest.fixture(autouse=True)
def custom_components_enabled(recorder_db_url, enable_custom_integrations):
    """Recorder's database configuration must precede HA creation."""


async def test_history_reads_actual_recorder_energy_and_price(recorder_mock, hass, tmp_path, freezer):
    from custom_components.charge_tally.history import HistorySource
    assert await async_setup_component(hass, "recorder", {"recorder": {"db_url": "sqlite:///:memory:"}})
    assert await async_wait_recorder(hass)
    start = dt_util.utcnow() + timedelta(seconds=1)
    freezer.move_to(start)
    hass.states.async_set("sensor.history_energy", "100", ENERGY)
    hass.states.async_set("sensor.history_price", "2", {"unit_of_measurement": "CNY/kWh"})
    await async_wait_recording_done(hass)
    freezer.move_to(start + timedelta(seconds=30))
    hass.states.async_set("sensor.history_energy", "100.060", ENERGY)
    hass.states.async_set("sensor.history_price", "unavailable", {"unit_of_measurement": "CNY/kWh"})
    await async_wait_recording_done(hass)
    source = HistorySource(hass)
    intervals = await source.async_intervals("sensor.history_energy", start, start + timedelta(seconds=30), True, 600)
    assert len(intervals) == 1
    assert Decimal(intervals[0]["energy_kwh"]) == Decimal(".060")
    assert intervals[0]["quality"] == []
    prices = await source.async_prices("sensor.history_price", start, start + timedelta(seconds=31), "CNY", "CNY/kWh")
    assert prices[0][1] == Decimal("2")
    assert prices[-1][1] is None
    assert await source.async_intervals("sensor.absent", start, dt_util.utcnow(), True, 600) == []


async def test_history_does_not_integrate_raw_power(recorder_mock, hass, freezer):
    from custom_components.charge_tally.history import HistorySource
    assert await async_setup_component(hass, "recorder", {"recorder": {"db_url": "sqlite:///:memory:"}})
    assert await async_wait_recorder(hass)
    start = dt_util.utcnow() + timedelta(seconds=1)
    freezer.move_to(start)
    hass.states.async_set("sensor.raw_power", "1000", POWER)
    await async_wait_recording_done(hass)
    freezer.move_to(start + timedelta(seconds=60))
    hass.states.async_set("sensor.raw_power", "0", POWER)
    await async_wait_recording_done(hass)
    assert await HistorySource(hass).async_intervals("sensor.raw_power", start, dt_util.utcnow(), True, 600) == []


async def test_runtime_preview_imports_missing_recorder_energy_once(recorder_mock, hass, tmp_path, freezer):
    start = dt_util.utcnow() + timedelta(seconds=1)
    freezer.move_to(start)
    hass.states.async_set("sensor.energy", "100", ENERGY)
    await async_wait_recording_done(hass)
    freezer.move_to(start + timedelta(seconds=30))
    hass.states.async_set("sensor.energy", "100.060", ENERGY)
    await async_wait_recording_done(hass)
    freezer.move_to(start + timedelta(seconds=60))
    entry, runtime = await setup_runtime(hass, tmp_path)
    payload = {"point_id": "point", "identity_id": "car", "start": start.isoformat(), "end": (start + timedelta(seconds=30)).isoformat()}
    preview = await runtime.async_command("preview", payload)
    assert Decimal(preview["record"]["energy_kwh"]) == Decimal(".060")
    assert "missing_energy" not in preview["record"]["quality"]
    second = await runtime.async_command("preview", payload)
    assert Decimal(second["record"]["energy_kwh"]) == Decimal(".060")
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_runtime_imports_actual_dynamic_price_history_not_current_price(recorder_mock, hass, tmp_path, freezer):
    start = dt_util.utcnow() + timedelta(seconds=1)
    freezer.move_to(start)
    hass.states.async_set("sensor.energy", "100", ENERGY)
    hass.states.async_set("sensor.price", "2", {"unit_of_measurement": "CNY/kWh"})
    await async_wait_recording_done(hass)
    freezer.move_to(start + timedelta(seconds=30))
    hass.states.async_set("sensor.energy", "100.060", ENERGY)
    hass.states.async_set("sensor.price", "9", {"unit_of_measurement": "CNY/kWh"})
    await async_wait_recording_done(hass)
    freezer.move_to(start + timedelta(seconds=60))
    entry, runtime = await setup_runtime(hass, tmp_path, price={"mode": "dynamic", "entity_id": "sensor.price", "unit": "CNY/kWh"})
    preview = await runtime.async_command("preview", {"point_id": "point", "identity_id": "car", "start": start.isoformat(), "end": (start + timedelta(seconds=30)).isoformat()})
    assert Decimal(preview["record"]["known_cost"]) == Decimal(".120")
    assert preview["record"]["cost_complete"] is True
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_reload_automatically_recovers_gap_from_actual_recorder(recorder_mock, hass, tmp_path, freezer):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await runtime.async_command("start", {"point_id": "point", "identity_id": "car", "request_id": "r1"})
    await async_wait_recording_done(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    for reading in ("100.3", "100.6", "101"):
        await tick(hass, freezer, 300)
        hass.states.async_set("sensor.energy", reading, ENERGY)
        await async_wait_recording_done(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    snapshot = await entry.runtime_data.async_snapshot()
    assert Decimal(snapshot["points"][0]["normalized_energy_kwh"]) == 1
    assert Decimal(snapshot["records"][0]["energy_kwh"]) == 1
    assert "missing_energy" not in snapshot["records"][0]["quality"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_api_manual_preview_stales_after_actual_recorder_price_import(recorder_mock, hass, tmp_path, freezer, hass_ws_client):
    start = dt_util.utcnow() + timedelta(seconds=1)
    freezer.move_to(start)
    hass.states.async_set("sensor.energy", "100", ENERGY)
    hass.states.async_set("sensor.price", "2", {"unit_of_measurement": "CNY/kWh"})
    await async_wait_recording_done(hass)
    end = start + timedelta(seconds=30)
    freezer.move_to(end)
    hass.states.async_set("sensor.energy", "110", ENERGY)
    await async_wait_recording_done(hass)
    freezer.move_to(end + timedelta(seconds=30))
    entry, runtime = await setup_runtime(hass, tmp_path, price={"mode": "dynamic", "entity_id": "sensor.price", "unit": "CNY/kWh"})
    client = await hass_ws_client(hass)
    data = {"point_id": "point", "identity_id": "car", "start": start.isoformat(), "end": end.isoformat()}
    await client.send_json({"id": 1, "type": "charge_tally/preview", **data, "energy_kwh": "10"})
    old = (await client.receive_json())["result"]
    assert old["record"]["cost_complete"] is False
    await runtime.async_command("preview", data)
    await client.send_json({"id": 2, "type": "charge_tally/commit", "token": old["token"], "request_id": "old-price"})
    assert (await client.receive_json())["error"]["code"] == "stale_preview"
    await client.send_json({"id": 3, "type": "charge_tally/preview", **data, "energy_kwh": "10"})
    fresh = (await client.receive_json())["result"]
    assert Decimal(fresh["record"]["known_cost"]) == 20
    assert fresh["record"]["cost_complete"] is True
    await client.send_json({"id": 4, "type": "charge_tally/commit", "token": fresh["token"], "request_id": "fresh-price"})
    assert (await client.receive_json())["success"] is True
    await hass.config_entries.async_unload(entry.entry_id)
