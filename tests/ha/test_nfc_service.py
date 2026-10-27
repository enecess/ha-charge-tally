"""Identity actions share runtime ordering and point permissions."""

import asyncio

import pytest
import voluptuous as vol
from homeassistant.auth.permissions import PolicyPermissions
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from test_nfc_manager import create_rule, setup_manager
from test_runtime import POWER, setup_runtime


async def call_select(hass, data, context=None):
    return await hass.services.async_call(
        "charge_tally",
        "select_identity",
        data,
        blocking=True,
        return_response=True,
        context=context,
    )


async def test_identity_action_exists_without_loaded_entry(hass):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "charge_tally", {})
    assert hass.services.has_service("charge_tally", "select_identity")
    with pytest.raises(ServiceValidationError, match="not loaded"):
        await call_select(hass, {"point_id": "point", "identity_id": "car"})


async def test_identity_action_keeps_active_record_and_checks_permissions(
    hass, tmp_path, hass_read_only_user
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    active = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "manual"}
    )
    result = await call_select(hass, {"point_id": "point", "identity_id": "car"})
    assert result == {"point_id": "point", "identity_id": "car"}
    snapshot = await runtime.async_snapshot()
    assert snapshot["points"][0]["selected_identity_id"] == "car"
    assert (
        snapshot["points"][0]["active_record"]["identity_id"]
        == active["identity_id"]
        == "unassigned"
    )
    hass_read_only_user.permissions = PolicyPermissions(
        {"entities": {"entity_ids": {}}}, None
    )
    with pytest.raises(Unauthorized):
        await call_select(
            hass,
            {"point_id": "point", "identity_id": "unassigned"},
            Context(user_id=hass_read_only_user.id),
        )
    with pytest.raises(vol.Invalid):
        await call_select(
            hass, {"point_id": "point", "identity_id": "car", "rule_id": "r"}
        )
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("change", ["delete", "version", "permission"])
async def test_queued_action_rechecks_guard_after_backup_gate(
    hass, tmp_path, hass_read_only_user, monkeypatch, change
):
    entry, runtime, manager, draft = await setup_manager(
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
    hass.states.async_set("sensor.power", "1000", POWER)
    await hass.async_block_till_done()
    before = (await runtime.async_snapshot())["points"][0]
    assert before["candidate_identity_id"] == "unassigned"
    runtime.nfc = manager
    rule = await create_rule(manager, draft)
    anchor = (await runtime.async_snapshot())["points"][0]["identity_entity_id"]
    hass_read_only_user.permissions = PolicyPermissions(
        {"entities": {"entity_ids": {anchor: True}}}, None
    )
    entered = asyncio.Event()
    original = runtime._gate.wait

    async def wait():
        entered.set()
        await original()

    await runtime.async_pre_backup()
    monkeypatch.setattr(runtime._gate, "wait", wait)
    task = asyncio.create_task(
        call_select(
            hass,
            {
                "point_id": "point",
                "identity_id": "car",
                "rule_id": rule["rule_id"],
                "rule_version": 1,
            },
            Context(user_id=hass_read_only_user.id),
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        if change == "permission":
            hass_read_only_user.permissions = PolicyPermissions(
                {"entities": {"entity_ids": {}}}, None
            )
        elif change == "delete":
            await manager.async_prepare(
                "delete", rule["rule_id"], None, rule["revision"], "delete"
            )
        else:
            prepared = await manager.async_prepare(
                "update", rule["rule_id"], draft, rule["revision"], "update"
            )
            await manager.async_confirm("update", prepared["desired_config"])
    finally:
        runtime.async_post_backup()
    with pytest.raises(
        Unauthorized if change == "permission" else ServiceValidationError
    ):
        await task
    after = (await runtime.async_snapshot())["points"][0]
    assert after["selected_identity_id"] == "unassigned"
    assert after["candidate_identity_id"] == "unassigned"
    assert after["candidate"] == before["candidate"]
    await hass.config_entries.async_unload(entry.entry_id)
