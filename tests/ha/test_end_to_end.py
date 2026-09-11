"""Exercise the installed integration from config flows to durable accounting."""
from decimal import Decimal

import pytest

from homeassistant.data_entry_flow import FlowResultType

from test_runtime import ENERGY, POWER, tick


async def configure(hass, result, data):
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], data)
    await hass.async_block_till_done()
    return result


async def add_point(hass, entry, name, mode):
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "point"), context={"source": "user"})
    result = await configure(hass, result, {"name": name, "input_mode": mode})
    measurement = {"resetting": True, "max_gap_seconds": 600}
    if mode == "energy":
        measurement["energy_entity"] = "sensor.e2e_energy"
    else:
        measurement.update(power_entity="sensor.e2e_power", detection_enabled=False)
    result = await configure(hass, result, {"measurement": measurement})
    result = await configure(hass, result, {"mode": "static" if mode == "energy" else "dynamic"})
    price = {"value": "0.5"} if mode == "energy" else {"entity_id": "sensor.e2e_price"}
    result = await configure(hass, result, price)
    result = await configure(hass, result, {"periods": ["daily", "monthly", "yearly"]})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    return next(sub.subentry_id for sub in entry.subentries.values() if sub.title == name)


@pytest.mark.freeze_time("2026-01-02T00:00:00+00:00")
async def test_flow_helpers_live_history_transfer_and_reload(hass, tmp_path, freezer, hass_ws_client):
    hass.config.config_dir = str(tmp_path)
    hass.config.time_zone = "Asia/Shanghai"
    hass.states.async_set("sensor.e2e_energy", "100", ENERGY)
    hass.states.async_set("sensor.e2e_power", "0", POWER)
    hass.states.async_set("sensor.e2e_price", "0.5", {"unit_of_measurement": "CNY/kWh"})
    result = await hass.config_entries.flow.async_init("charge_tally", context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"currency": "CNY"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    # Older HA opens the first point manually from the integration page.
    if "next_flow" in result:
        hass.config_entries.subentries.async_abort(result["next_flow"][1])
    point_a = await add_point(hass, entry, "Metered garage", "energy")
    point_b = await add_point(hass, entry, "Power garage", "power")
    identities = []
    for name in ("Shared car", "Transferred car"):
        form = await hass.config_entries.subentries.async_init((entry.entry_id, "identity"), context={"source": "user"})
        assert (await configure(hass, form, {"name": name, "enabled": True}))["type"] == FlowResultType.CREATE_ENTRY
        identities.append(next(sub.subentry_id for sub in entry.subentries.values() if sub.title == name))
    assert len(hass.config_entries.async_entries("integration")) == 1
    assert len(hass.config_entries.async_entries("utility_meter")) == 6
    client = await hass_ws_client(hass)
    sequence = 0

    async def ws(command, **data):
        nonlocal sequence
        sequence += 1
        await client.send_json({"id": sequence, "type": "charge_tally/" + command, **data})
        response = await client.receive_json()
        assert response["success"], response
        return response["result"]

    async def action(name, **data):
        return await hass.services.async_call("charge_tally", name, data, blocking=True, return_response=True)

    snapshot = await ws("snapshot")
    assert len(snapshot["points"]) == 2
    for point in snapshot["points"]:
        await hass.services.async_call("select", "select_option", {
            "entity_id": point["identity_entity_id"], "option": "Shared car"
        }, blocking=True)
    hass.states.async_set("sensor.e2e_power", "3600", POWER)
    await hass.async_block_till_done()
    starts = [await action("start", point_id=point, request_id="start-" + point) for point in (point_a, point_b)]
    assert await action("start", point_id=point_a, request_id="start-" + point_a) == starts[0]
    # Changing the next identity cannot transfer either active record.
    for point in snapshot["points"]:
        await hass.services.async_call("select", "select_option", {
            "entity_id": point["identity_entity_id"], "option": "Unassigned"
        }, blocking=True)
    # Clock jumps intentionally bypass wall-clock WebSocket heartbeat replies.
    await client.close()
    await tick(hass, freezer, 60)
    hass.states.async_set("sensor.e2e_energy", "100.060", ENERGY)
    hass.states.async_set("sensor.e2e_price", "unavailable", {"unit_of_measurement": "CNY/kWh"})
    await hass.async_block_till_done()
    await tick(hass, freezer, 60)
    hass.states.async_set("sensor.e2e_energy", "100.120", ENERGY)
    hass.states.async_set("sensor.e2e_power", "0", POWER)
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)
    snapshot = await ws("snapshot")
    for point in snapshot["points"]:
        record = point["active_record"]
        assert record["identity_id"] == identities[0]
        assert Decimal(record["energy_kwh"]) == Decimal("0.120")
        assert Decimal(record["known_cost"]) == (Decimal("0.060") if point["id"] == point_a else Decimal("0.030"))
        assert record["cost_complete"] == (point["id"] == point_a)
        assert Decimal(hass.states.get(point["utility_entities"]["daily"]).state) == Decimal("0.120")
        await action("end", record_id=record["id"], expected_revision=record["revision"], request_id="end-" + point["id"])
    # Three hours span New Year locally: one hour gets 7 kWh, two get 14 kWh.
    preview = await ws("preview", point_id=point_a, identity_id=identities[0],
        start="2025-12-31T23:00:00+08:00", end="2026-01-01T02:00:00+08:00", energy_kwh="21", cost=None)
    assert (await ws("records"))["total"] == 2
    assert [Decimal(segment["energy_kwh"]) for segment in preview["segments"]] == [Decimal(7), Decimal(14)]
    assert preview["record"]["cost_complete"] is False
    assert "manual" in preview["record"]["quality"]
    historical = await ws("commit", token=preview["token"], request_id="history")
    assert await ws("commit", token=preview["token"], request_id="history") == historical
    before = (await ws("snapshot"))["summary"]
    assert Decimal(before["energy_kwh"]) == Decimal("21.240")
    assert Decimal(before["known_cost"]) == Decimal("0.090")
    assert before["cost_complete"] is False
    records = (await ws("records"))["records"]
    for record in records:
        transferred = await action("reassign", record_id=record["id"], identity_id=identities[1],
            expected_revision=record["revision"], request_id="transfer-" + record["id"])
        assert transferred["energy_kwh"] == record["energy_kwh"]
        assert transferred["known_cost"] == record["known_cost"]
    after = await ws("snapshot")
    assert after["summary"] == before
    totals = {identity["id"]: identity["summaries"]["total"] for identity in after["identities"]}
    assert Decimal(totals[identities[0]]["energy_kwh"]) == 0
    assert Decimal(totals[identities[1]]["energy_kwh"]) == Decimal("21.240")
    assert totals[identities[1]]["cost_complete"] is False
    previous_year = await ws("query", identity_id=identities[1], start="2025-01-01T00:00:00+08:00", end="2026-01-01T00:00:00+08:00")
    assert Decimal(previous_year["energy_kwh"]) == 7
    assert previous_year["completed_count"] == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (await ws("snapshot"))["summary"] == before
    assert (await ws("records"))["total"] == 3
    assert len(hass.config_entries.async_entries("integration")) == 1
    assert len(hass.config_entries.async_entries("utility_meter")) == 6
    assert await hass.config_entries.async_unload(entry.entry_id)
