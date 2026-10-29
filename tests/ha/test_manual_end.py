"""Manual end stays usable while meter samples update an active record."""

from decimal import Decimal

import pytest
from test_runtime import ENERGY, POWER, setup_runtime, tick


@pytest.mark.parametrize("source", ["manual", "automatic"])
async def test_end_by_record_id_survives_measurements_and_retries(
    hass, tmp_path, hass_ws_client, freezer, source
):
    entry, runtime = await setup_runtime(
        hass,
        tmp_path,
        detection={
            "enabled": True,
            "start_w": "500",
            "end_w": "100",
            "start_seconds": 1,
            "end_seconds": 60,
        },
    )
    hass.states.async_set("sensor.power", "7000", POWER)
    await hass.async_block_till_done()
    if source == "manual":
        await runtime.async_command(
            "start", {"point_id": "point", "request_id": "start"}
        )
    else:
        await tick(hass, freezer, 1)
    record = runtime.snapshot["points"][0]["active_record"]
    assert record["source"] == source

    await tick(hass, freezer, 5)
    hass.states.async_set("sensor.energy", "101", ENERGY)
    await hass.async_block_till_done()
    current = runtime.snapshot["points"][0]["active_record"]
    assert current["revision"] > record["revision"]

    client = await hass_ws_client(hass)
    request = {
        "type": "call_service",
        "domain": "charge_tally",
        "service": "end",
        "return_response": True,
        "service_data": {
            "record_id": record["id"],
            "request_id": "end",
        },
    }
    # Explicit revision guards remain available to automation callers.
    await client.send_json(
        {
            **request,
            "id": 1,
            "service_data": {
                **request["service_data"],
                "expected_revision": record["revision"],
            },
        }
    )
    conflict = await client.receive_json()
    assert conflict["success"] is False
    assert conflict["error"]["translation_key"] == "conflict"

    await client.send_json({**request, "id": 2})
    response = await client.receive_json()
    assert response["success"], response
    ended = response["result"]["response"]
    assert ended["id"] == record["id"]
    assert ended["status"] == "ended"
    assert Decimal(ended["energy_kwh"]) == Decimal(current["energy_kwh"])
    assert Decimal(ended["known_cost"]) == Decimal(current["known_cost"])
    assert runtime.snapshot["points"][0]["active_record"] is None
    assert runtime.snapshot["points"][0]["detection_state"] == "blocked"

    await tick(hass, freezer, 5)
    await client.send_json({**request, "id": 3})
    assert (await client.receive_json())["result"]["response"] == ended

    replacement = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "next-record"}
    )
    await client.send_json({**request, "id": 4})
    assert (await client.receive_json())["result"]["response"] == ended
    await client.send_json(
        {
            **request,
            "id": 5,
            "service_data": {**request["service_data"], "request_id": "old-record"},
        }
    )
    assert (await client.receive_json())["success"] is False
    assert runtime.snapshot["points"][0]["active_record"]["id"] == replacement["id"]
    await hass.config_entries.async_unload(entry.entry_id)
