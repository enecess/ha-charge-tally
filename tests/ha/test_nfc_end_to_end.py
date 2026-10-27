"""Run managed NFC rules through HA's actual configuration and automation engines."""

import pytest
from homeassistant.components.tag import TAG_DATA, async_scan_tag
from homeassistant.helpers import entity_registry as er
from test_nfc_api import request
from test_nfc_manager import setup_manager
from test_nfc_native_contract import async_setup_nfc_native
from test_runtime import POWER, tick


async def configure_rule(hass, client, ws, entry, draft, rule=None, operation="create"):
    prepared = await request(
        ws,
        1 if rule is None else 3,
        entry,
        "prepare",
        kind="create" if rule is None else "update",
        rule_id=rule["rule_id"] if rule else None,
        draft=draft,
        expected_revision=rule["revision"] if rule else None,
        operation_id=operation,
    )
    assert prepared["success"], prepared
    change = prepared["result"]
    path = "/api/config/automation/config/" + change["automation_id"]
    response = await client.post(path, json=change["desired_config"])
    assert response.status == 200, await response.text()
    actual = await (await client.get(path)).json()
    confirmed = await request(
        ws,
        2 if rule is None else 4,
        entry,
        "confirm",
        operation_id=operation,
        observed_config=actual,
    )
    assert confirmed["success"], confirmed
    await hass.async_block_till_done()
    return confirmed["result"]


@pytest.mark.parametrize("recording", ["manual", "pending_start"])
async def test_real_rule_updates_pending_identity_preserves_manual_record_and_pause(
    hass, tmp_path, hass_client, hass_ws_client, freezer, recording
):
    entry, runtime, _, draft = await setup_manager(
        hass,
        tmp_path,
        detection={
            "enabled": True,
            "start_w": 100,
            "end_w": 10,
            "start_seconds": 60,
            "end_seconds": 60,
        },
    )
    await async_setup_nfc_native(hass, tmp_path)
    client, ws = await hass_client(), await hass_ws_client(hass)
    rule = await configure_rule(hass, client, ws, entry, draft)
    if recording == "manual":
        active = await runtime.async_command(
            "start", {"point_id": "point", "request_id": "manual"}
        )
    else:
        hass.states.async_set("sensor.power", "1000", POWER)
        await hass.async_block_till_done()
    before = (await runtime.async_snapshot())["points"][0]
    await async_scan_tag(hass, "tag-a", draft["device_bindings"][0]["device_id"])
    await hass.async_block_till_done()
    point = (await runtime.async_snapshot())["points"][0]
    assert point["selected_identity_id"] == "car"
    if recording == "manual":
        assert point["active_record"]["id"] == active["id"]
        assert point["active_record"]["identity_id"] == "unassigned"
    else:
        assert point["active_record"] is None
        assert point["candidate_identity_id"] == "car"
        assert point["candidate"] == before["candidate"]
        await tick(hass, freezer, 61)
        confirmed = (await runtime.async_snapshot())["points"][0]
        assert confirmed["active_record"]["identity_id"] == "car"
        assert confirmed["active_record"]["start"] == before["candidate"]
    entity = er.async_get(hass).async_get_entity_id(
        "automation", "automation", rule["automation_id"]
    )
    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": entity}, blocking=True
    )
    rule = await configure_rule(hass, client, ws, entry, draft, rule, "update")
    assert hass.states.get(entity).state == "off"
    await runtime.async_select_identity("point", "unassigned")
    await async_scan_tag(hass, "tag-a", draft["device_bindings"][0]["device_id"])
    await hass.async_block_till_done()
    assert (await runtime.async_snapshot())["points"][0][
        "selected_identity_id"
    ] == "unassigned"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_deleted_tag_is_not_silently_rebound_when_reader_registers_it_again(
    hass, tmp_path, hass_client, hass_ws_client
):
    entry, runtime, _, draft = await setup_manager(hass, tmp_path)
    await async_setup_nfc_native(hass, tmp_path)
    client, ws = await hass_client(), await hass_ws_client(hass)
    await configure_rule(hass, client, ws, entry, draft)
    await hass.data[TAG_DATA].async_delete_item("tag-a")
    await hass.async_block_till_done()
    await async_scan_tag(hass, "tag-a", draft["device_bindings"][0]["device_id"])
    await hass.async_block_till_done()
    await async_scan_tag(hass, "tag-a", draft["device_bindings"][0]["device_id"])
    await hass.async_block_till_done()
    assert (await runtime.async_snapshot())["points"][0][
        "selected_identity_id"
    ] == "unassigned"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_shared_tag_selects_each_point_and_survives_identity_rename(
    hass, tmp_path, hass_client, hass_ws_client
):
    from test_api import second_point

    entry, runtime, manager, draft = await setup_manager(hass, tmp_path)
    await second_point(hass, entry, runtime)
    await async_setup_nfc_native(hass, tmp_path)
    client = await hass_client()
    ws = await hass_ws_client(hass)
    await configure_rule(hass, client, ws, entry, draft)
    other = {
        **draft,
        "point_id": "other",
        "device_bindings": [],
        "default_identity_id": "car",
    }
    prepared = await manager.async_prepare("create", None, other, None, "other")
    path = "/api/config/automation/config/" + prepared["automation_id"]
    assert (await client.post(path, json=prepared["desired_config"])).status == 200
    await manager.async_confirm("other", await (await client.get(path)).json())
    sub = entry.subentries["car"]
    hass.config_entries.async_update_subentry(
        entry, sub, data={**sub.data, "name": "Renamed car"}
    )
    await hass.async_block_till_done()
    await async_scan_tag(hass, "tag-a", draft["device_bindings"][0]["device_id"])
    await hass.async_block_till_done()
    snapshot = await runtime.async_snapshot()
    assert {p["id"]: p["selected_identity_id"] for p in snapshot["points"]} == {
        "point": "car",
        "other": "car",
    }
    assert all(p["active_record"] is None for p in snapshot["points"])
    await hass.config_entries.async_unload(entry.entry_id)
