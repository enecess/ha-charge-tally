"""Native record meters retain the latest ended bill without implying activity."""

from decimal import Decimal

from test_runtime import ENERGY, setup_runtime, tick


async def test_latest_bill_survives_end_new_record_and_void(hass, tmp_path, freezer):
    entry, runtime = await setup_runtime(hass, tmp_path)
    first = await runtime.async_command(
        "start", {"point_id": "point", "identity_id": "car", "request_id": "one"}
    )
    await tick(hass, freezer, 30)
    hass.states.async_set("sensor.energy", "101", ENERGY)
    await hass.async_block_till_done()
    await runtime.async_command(
        "end", {"record_id": first["id"], "request_id": "end-one"}
    )
    assert runtime.snapshot["points"][0]["active_record"] is None
    assert Decimal(hass.states.get("sensor.garage_record_cost").state) == 2
    assert Decimal(hass.states.get("sensor.garage_record_energy").state) == 1
    assert (
        hass.states.get("sensor.garage_record_cost").attributes["record_status"]
        == "ended"
    )
    assert "record_id" not in hass.states.get("sensor.garage_status").attributes
    second = await runtime.async_command(
        "start", {"point_id": "point", "identity_id": "car", "request_id": "two"}
    )
    assert Decimal(hass.states.get("sensor.garage_record_cost").state) == 0
    assert (
        hass.states.get("sensor.garage_record_cost").attributes["record_id"]
        == second["id"]
    )
    await tick(hass, freezer, 30)
    hass.states.async_set("sensor.energy", "103", ENERGY)
    await hass.async_block_till_done()
    ended = await runtime.async_command(
        "end", {"record_id": second["id"], "request_id": "end-two"}
    )
    assert Decimal(hass.states.get("sensor.garage_record_cost").state) == 4
    await runtime.async_command(
        "void", {"record_id": second["id"], "expected_revision": ended["revision"]}
    )
    assert Decimal(hass.states.get("sensor.garage_record_cost").state) == 2
    assert (
        hass.states.get("sensor.garage_record_cost").attributes["record_id"]
        == first["id"]
    )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_timeout_keeps_cost_numeric_and_discloses_ended_reason(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await runtime.async_command(
        "start", {"point_id": "point", "identity_id": "car", "request_id": "one"}
    )
    await tick(hass, freezer, 30)
    hass.states.async_set("sensor.energy", "101", ENERGY)
    await hass.async_block_till_done()
    await tick(hass, freezer, 30)
    hass.states.async_set("sensor.energy", "unavailable", ENERGY)
    await hass.async_block_till_done()
    assert Decimal(hass.states.get("sensor.garage_record_cost").state) == 2
    await tick(hass, freezer, 300)
    state = hass.states.get("sensor.garage_record_cost")
    assert Decimal(state.state) == 2
    assert state.attributes["end_reason"] == "source_unavailable"
    assert state.attributes["record_status"] == "ended"
    assert state.attributes["cost_complete"] is False
    assert Decimal(hass.states.get("sensor.car_total_cost").state) == 2
    assert await hass.config_entries.async_unload(entry.entry_id)
