"""Exercise the installed integration from config flows to durable accounting."""

import asyncio
import shutil
from decimal import Decimal

import pytest
from homeassistant.auth.permissions import PolicyPermissions
from homeassistant.data_entry_flow import FlowResultType
from test_runtime import ENERGY, POWER, tick


async def configure(hass, result, data):
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], data
    )
    await hass.async_block_till_done()
    return result


async def add_point(hass, entry, name, mode):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "point"), context={"source": "user"}
    )
    result = await configure(hass, result, {"name": name, "input_mode": mode})
    measurement = {"resetting": True, "max_gap_seconds": 600}
    if mode != "power":
        measurement["energy_entity"] = "sensor.e2e_energy"
    if mode != "energy":
        measurement.update(
            power_entity="sensor.e2e_power", detection_enabled=mode == "energy_power"
        )
    result = await configure(hass, result, {"measurement": measurement})
    if mode == "energy_power":
        result = await configure(
            hass,
            result,
            {
                "start_w": 500,
                "end_w": 100,
                "start_seconds": 30,
                "end_seconds": 60,
            },
        )
    result = await configure(
        hass, result, {"mode": "static" if mode == "energy" else "dynamic"}
    )
    price = {"value": "0.5"} if mode == "energy" else {"entity_id": "sensor.e2e_price"}
    result = await configure(hass, result, price)
    result = await configure(hass, result, {"periods": ["daily", "monthly", "yearly"]})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    return next(
        sub.subentry_id for sub in entry.subentries.values() if sub.title == name
    )


@pytest.mark.freeze_time("2026-01-02T00:00:00+00:00")
async def test_flow_helpers_live_history_transfer_and_reload(
    hass, tmp_path, freezer, hass_ws_client
):
    hass.config.config_dir = str(tmp_path)
    hass.config.time_zone = "Asia/Shanghai"
    hass.states.async_set("sensor.e2e_energy", "100", ENERGY)
    hass.states.async_set("sensor.e2e_power", "0", POWER)
    hass.states.async_set("sensor.e2e_price", "0.5", {"unit_of_measurement": "CNY/kWh"})
    result = await hass.config_entries.flow.async_init(
        "charge_tally", context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"currency": "CNY"}
    )
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
        form = await hass.config_entries.subentries.async_init(
            (entry.entry_id, "identity"), context={"source": "user"}
        )
        assert (await configure(hass, form, {"name": name, "enabled": True}))[
            "type"
        ] == FlowResultType.CREATE_ENTRY
        identities.append(
            next(
                sub.subentry_id
                for sub in entry.subentries.values()
                if sub.title == name
            )
        )
    assert len(hass.config_entries.async_entries("integration")) == 1
    assert len(hass.config_entries.async_entries("utility_meter")) == 6
    client = await hass_ws_client(hass)
    sequence = 0

    async def ws(command, **data):
        nonlocal sequence
        sequence += 1
        await client.send_json(
            {"id": sequence, "type": "charge_tally/" + command, **data}
        )
        response = await client.receive_json()
        assert response["success"], response
        return response["result"]

    async def action(name, **data):
        return await hass.services.async_call(
            "charge_tally", name, data, blocking=True, return_response=True
        )

    snapshot = await ws("snapshot")
    assert len(snapshot["points"]) == 2
    for point in snapshot["points"]:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": point["identity_entity_id"], "option": "Shared car"},
            blocking=True,
        )
    hass.states.async_set("sensor.e2e_power", "3600", POWER)
    await hass.async_block_till_done()
    # Some HA versions defer the helper's state notification beyond task draining.
    async with asyncio.timeout(5):
        while not entry.runtime_data._store.states[point_b].get("available"):
            await asyncio.sleep(0)
    await hass.async_block_till_done()
    starts = [
        await action("start", point_id=point, request_id="start-" + point)
        for point in (point_a, point_b)
    ]
    assert (
        await action("start", point_id=point_a, request_id="start-" + point_a)
        == starts[0]
    )
    # Changing the next identity cannot transfer either active record.
    for point in snapshot["points"]:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": point["identity_entity_id"], "option": "Unassigned"},
            blocking=True,
        )
    # Clock jumps intentionally bypass wall-clock WebSocket heartbeat replies.
    await client.close()
    await tick(hass, freezer, 60)
    hass.states.async_set("sensor.e2e_energy", "100.060", ENERGY)
    hass.states.async_set(
        "sensor.e2e_price", "unavailable", {"unit_of_measurement": "CNY/kWh"}
    )
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
        assert Decimal(record["known_cost"]) == (
            Decimal("0.060") if point["id"] == point_a else Decimal("0.030")
        )
        assert record["cost_complete"] == (point["id"] == point_a)
        assert Decimal(
            hass.states.get(point["utility_entities"]["daily"]).state
        ) == Decimal("0.120")
        await action(
            "end",
            record_id=record["id"],
            expected_revision=record["revision"],
            request_id="end-" + point["id"],
        )
    # Three hours span New Year locally: one hour gets 7 kWh, two get 14 kWh.
    preview = await ws(
        "preview",
        point_id=point_a,
        identity_id=identities[0],
        start="2025-12-31T23:00:00+08:00",
        end="2026-01-01T02:00:00+08:00",
        energy_kwh="21",
        cost=None,
    )
    assert (await ws("records"))["total"] == 2
    assert [Decimal(segment["energy_kwh"]) for segment in preview["segments"]] == [
        Decimal(7),
        Decimal(14),
    ]
    assert preview["record"]["cost_complete"] is False
    assert "manual" in preview["record"]["quality"]
    historical = await ws("commit", token=preview["token"], request_id="history")
    assert (
        await ws("commit", token=preview["token"], request_id="history") == historical
    )
    before = (await ws("snapshot"))["summary"]
    assert Decimal(before["energy_kwh"]) == Decimal("21.240")
    assert Decimal(before["known_cost"]) == Decimal("0.090")
    assert before["cost_complete"] is False
    records = (await ws("records"))["records"]
    for record in records:
        transferred = await action(
            "reassign",
            record_id=record["id"],
            identity_id=identities[1],
            expected_revision=record["revision"],
            request_id="transfer-" + record["id"],
        )
        assert transferred["energy_kwh"] == record["energy_kwh"]
        assert transferred["known_cost"] == record["known_cost"]
    after = await ws("snapshot")
    assert after["summary"] == before
    totals = {
        identity["id"]: identity["summaries"]["total"]
        for identity in after["identities"]
    }
    assert Decimal(totals[identities[0]]["energy_kwh"]) == 0
    assert Decimal(totals[identities[1]]["energy_kwh"]) == Decimal("21.240")
    assert totals[identities[1]]["cost_complete"] is False
    previous_year = await ws(
        "query",
        identity_id=identities[1],
        start="2025-01-01T00:00:00+08:00",
        end="2026-01-01T00:00:00+08:00",
    )
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


@pytest.mark.freeze_time("2026-09-22T00:00:00+00:00")
async def test_automatic_accounting_edit_restore_backfill_and_confirmed_archive(
    hass,
    tmp_path,
    freezer,
    hass_ws_client,
    hass_read_only_user,
    hass_read_only_access_token,
):
    from test_archive_options import archive_flow, choose

    from custom_components.charge_tally.backup import (
        async_post_backup,
        async_pre_backup,
    )

    hass.config.config_dir = str(tmp_path)
    hass.config.time_zone = "Asia/Shanghai"
    hass.states.async_set("sensor.e2e_energy", "100", ENERGY)
    hass.states.async_set("sensor.e2e_power", "0", POWER)
    hass.states.async_set("sensor.e2e_price", "0.5", {"unit_of_measurement": "CNY/kWh"})
    form = await hass.config_entries.flow.async_init(
        "charge_tally", context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"currency": "CNY"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    if "next_flow" in result:
        hass.config_entries.subentries.async_abort(result["next_flow"][1])
    point_id = await add_point(hass, entry, "Automatic garage", "energy_power")
    runtime = entry.runtime_data
    hass.states.async_set("sensor.e2e_power", "1000", POWER)
    await hass.async_block_till_done()
    await tick(hass, freezer, 31)
    active = (await runtime.async_snapshot())["points"][0]["active_record"]
    assert active["source"] == "automatic"
    for reading in ("100.010", "100.030", "100.060"):
        await tick(hass, freezer, 30)
        hass.states.async_set("sensor.e2e_energy", reading, ENERGY)
        await hass.async_block_till_done()
    detail = await runtime.async_query("record", {"record_id": active["id"]})
    assert Decimal(detail["record"]["energy_kwh"]) == Decimal("0.060")
    assert Decimal(detail["record"]["known_cost"]) == Decimal("0.030")
    assert len(detail["revisions"]) == 1
    hass.states.async_set("sensor.e2e_power", "0", POWER)
    await hass.async_block_till_done()
    await tick(hass, freezer, 61)
    client = await hass_ws_client(hass)
    sequence = 0

    async def ws(command, **data):
        nonlocal sequence
        sequence += 1
        await client.send_json(
            {"id": sequence, "type": "charge_tally/" + command, **data}
        )
        response = await client.receive_json()
        assert response["success"], response
        return response["result"]

    detail = await ws("records", record_id=active["id"])
    assert detail["record"]["status"] == "ended"
    assert len(detail["revisions"]) == 2
    assert len(detail["segments"]) == 1
    for period in ("hour", "month", "year"):
        summary = await ws(
            "query",
            point_id=point_id,
            start="2026-01-01T00:00:00+08:00",
            end="2027-01-01T00:00:00+08:00",
            bucket_period=period,
        )
        assert Decimal(summary["energy_kwh"]) == Decimal("0.060")
        assert Decimal(summary["known_cost"]) == Decimal("0.030")
        assert sum(
            Decimal(bucket["energy_kwh"]) for bucket in summary["buckets"]
        ) == Decimal("0.060")
        assert summary["completed_count"] == 1
    revision = detail["record"]["revision"]
    preview = await ws(
        "preview",
        record_id=active["id"],
        expected_revision=revision,
        energy_kwh="0.123456789123456789",
        cost="0.0617283945617283945",
        note="Reviewed",
    )
    assert len((await ws("records", record_id=active["id"]))["revisions"]) == 2
    edited = await ws(
        "commit",
        token=preview["token"],
        expected_revision=revision,
        request_id="edited",
    )
    assert Decimal(edited["energy_kwh"]) == Decimal("0.123456789123456789")
    assert Decimal(edited["known_cost"]) == Decimal("0.0617283945617283945")
    assert len((await ws("records", record_id=active["id"]))["revisions"]) == 3

    # A permission change must take effect for the next request on the same connection.
    anchor = (await ws("snapshot"))["points"][0]["identity_entity_id"]
    hass_read_only_user.permissions = PolicyPermissions(
        {"entities": {"entity_ids": {anchor: True}}}, None
    )
    restricted = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    await restricted.send_json(
        {"id": 1, "type": "charge_tally/records", "record_id": active["id"]}
    )
    assert (await restricted.receive_json())["result"]["record"]["id"] == active["id"]
    hass_read_only_user.permissions = PolicyPermissions(
        {"entities": {"entity_ids": {}}}, None
    )
    await restricted.send_json(
        {"id": 2, "type": "charge_tally/records", "record_id": active["id"]}
    )
    assert (await restricted.receive_json())["error"]["code"] == "unauthorized"
    await restricted.close()
    before = (await ws("snapshot"))["summary"]
    saved_detail = await ws("records", record_id=active["id"])
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert (await ws("snapshot"))["summary"] == before
    assert await ws("records", record_id=active["id"]) == saved_detail
    await async_pre_backup(hass)
    await async_post_backup(hass)
    backup = tmp_path / "charge_tally" / "ledger.backup.sqlite3"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_add_executor_job(
        shutil.copyfile, backup, tmp_path / "charge_tally" / "ledger.sqlite3"
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (await ws("snapshot"))["summary"] == before
    assert await ws("records", record_id=active["id"]) == saved_detail
    history = await ws(
        "preview",
        point_id=point_id,
        identity_id="unassigned",
        start="2026-09-20T00:00:00+08:00",
        end="2026-09-20T01:00:00+08:00",
        energy_kwh="1",
        cost="0.5",
    )
    historical = await ws("commit", token=history["token"], request_id="backfill")
    total = (await ws("snapshot"))["summary"]
    assert Decimal(total["energy_kwh"]) == Decimal("1.123456789123456789")
    assert Decimal(total["known_cost"]) == Decimal("0.5617283945617283945")
    assert (await ws("records"))["total"] == 2
    runtime = entry.runtime_data
    unfinished = await runtime.async_command(
        "start", {"point_id": point_id, "request_id": "unfinished"}
    )
    hass.config_entries.async_remove_subentry(entry, point_id)
    await hass.async_block_till_done()
    runtime = entry.runtime_data
    form = await archive_flow(hass, entry, "point")
    form = await choose(hass, form, {"object_id": [point_id]})
    assert form["description_placeholders"]["records"] == "3"
    assert form["description_placeholders"]["active"] == "1"
    form = await choose(hass, form, {"confirm": False})
    assert form["errors"] == {"base": "confirm_required"}
    assert (await runtime.async_query("records", {}))["total"] == 3
    form = await choose(hass, form, {"confirm": True})
    assert form["step_id"] == "archive_done"
    for record in (edited, historical, unfinished):
        assert (
            await runtime._read(runtime._store.ledger.get_record, record["id"]) is None
        )
        assert (
            await runtime._read(runtime._store.ledger.list_revisions, record["id"])
            == []
        )
        assert (
            await runtime._read(runtime._store.ledger.list_segments, record["id"]) == []
        )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    final = await ws("snapshot")
    assert final["points"] == final["archived_points"] == []
    assert Decimal(final["summary"]["energy_kwh"]) == 0
    assert (await ws("records"))["total"] == 0
    assert point_id not in entry.runtime_data._store.states
    assert await hass.config_entries.async_unload(entry.entry_id)
