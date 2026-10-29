"""HA callbacks close persistent outages without a subsequent meter event."""

from datetime import timedelta
from decimal import Decimal

import pytest
from homeassistant.util import dt as dt_util
from test_runtime import ENERGY, setup_runtime, tick


async def test_unavailable_timer_backdates_end_without_another_source_event(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    record = await runtime.async_command(
        "start", {"point_id": "point", "identity_id": "car", "request_id": "start"}
    )
    await tick(hass, freezer, 60)
    hass.states.async_set("sensor.energy", "101", ENERGY)
    await hass.async_block_till_done()
    await tick(hass, freezer, 30)
    offline = dt_util.utcnow()
    hass.states.async_set("sensor.energy", "unavailable", ENERGY)
    await hass.async_block_till_done()
    await tick(hass, freezer, 299)
    assert runtime.snapshot["points"][0]["active_record"]["id"] == record["id"]
    await tick(hass, freezer, 1)
    assert runtime.snapshot["points"][0]["active_record"] is None
    ended = next(
        item for item in runtime.snapshot["records"] if item["id"] == record["id"]
    )
    assert ended["end"] == offline.isoformat()
    assert ended["end_reason"] == "source_unavailable"
    assert Decimal(ended["known_cost"]) == 2
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not runtime._timers


@pytest.mark.parametrize("elapsed", [299, 300, 320])
async def test_energy_recovery_checks_deadline_without_waiting_for_timer(
    hass, tmp_path, freezer, elapsed
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    record = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "start"}
    )
    await tick(hass, freezer, 60)
    offline = dt_util.utcnow()
    hass.states.async_set("sensor.energy", "unavailable", ENERGY)
    await hass.async_block_till_done()
    freezer.move_to(offline + timedelta(seconds=elapsed))
    hass.states.async_set("sensor.energy", "104", ENERGY)
    await hass.async_block_till_done()
    current = next(
        item for item in runtime.snapshot["records"] if item["id"] == record["id"]
    )
    assert (current["status"] == "ended") is (elapsed >= 300)
    if elapsed >= 300:
        assert current["end"] == offline.isoformat()
        assert Decimal(current["known_cost"]) == 0
    else:
        assert Decimal(current["known_cost"]) == 8
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_reload_preserves_the_original_unavailable_deadline(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    record = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "start"}
    )
    await tick(hass, freezer, 60)
    offline = dt_util.utcnow()
    hass.states.async_set("sensor.energy", "unavailable", ENERGY)
    await hass.async_block_till_done()
    await tick(hass, freezer, 180)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass, freezer, 120)
    current = next(
        item
        for item in entry.runtime_data.snapshot["records"]
        if item["id"] == record["id"]
    )
    assert current["status"] == "ended"
    assert current["end"] == offline.isoformat()
    assert await hass.config_entries.async_unload(entry.entry_id)
