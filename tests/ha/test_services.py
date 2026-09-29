"""Services use trusted context and the same point authorization as WS."""

import pytest
import voluptuous as vol
from homeassistant.auth.permissions import PolicyPermissions
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from test_api import second_point
from test_runtime import setup_runtime


@pytest.mark.parametrize(
    "service,data",
    [
        ("start", {"point_id": "point", "request_id": "start"}),
        ("end", {"point_id": "point", "request_id": "end", "expected_revision": 1}),
        (
            "reassign",
            {
                "record_id": "record",
                "identity_id": "car",
                "request_id": "assign",
                "expected_revision": 1,
            },
        ),
    ],
)
async def test_services_are_available_without_a_loaded_entry(hass, service, data):
    """Failed or absent entries leave actions available with a useful error."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "charge_tally", {})
    assert hass.services.has_service("charge_tally", service)
    with pytest.raises(ServiceValidationError, match="not loaded"):
        await hass.services.async_call("charge_tally", service, data, blocking=True)


async def test_service_denies_unowned_target_but_allows_trusted_automation(
    hass, tmp_path, hass_read_only_user
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    assert hass.services.has_service("charge_tally", "start")
    hass_read_only_user.permissions = PolicyPermissions(
        {"entities": {"entity_ids": {}}}, None
    )
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "charge_tally",
            "start",
            {"point_id": "point", "request_id": "denied"},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
            return_response=True,
        )
    assert (await runtime.async_query("records", {}, point_ids=["point"]))["total"] == 0
    result = await hass.services.async_call(
        "charge_tally",
        "start",
        {"point_id": "point", "request_id": "trusted"},
        blocking=True,
        return_response=True,
    )
    assert result["point_id"] == "point"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_services_select_target_end_revision_and_forbidden_time(
    hass, tmp_path, hass_read_only_user, freezer
):
    from test_runtime import tick

    entry, runtime = await setup_runtime(hass, tmp_path)
    anchor = (await runtime.async_snapshot())["points"][0]["identity_entity_id"]
    hass_read_only_user.permissions = PolicyPermissions(
        {"entities": {"entity_ids": {anchor: True}}}, None
    )
    context = Context(user_id=hass_read_only_user.id)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            "charge_tally",
            "start",
            {"entity_id": anchor, "request_id": "past", "at": "2025-01-01T00:00:00Z"},
            blocking=True,
            context=context,
        )
    first = await hass.services.async_call(
        "charge_tally",
        "start",
        {"request_id": "start"},
        target={"entity_id": anchor},
        blocking=True,
        return_response=True,
        context=context,
    )
    await tick(hass, freezer, 2)
    ended = await hass.services.async_call(
        "charge_tally",
        "end",
        {"request_id": "end", "expected_revision": first["revision"]},
        target={"entity_id": anchor},
        blocking=True,
        return_response=True,
        context=context,
    )
    assert ended["status"] == "ended"
    assert ended["id"] == first["id"]
    repeated = await hass.services.async_call(
        "charge_tally",
        "end",
        {"request_id": "end", "expected_revision": first["revision"]},
        target={"entity_id": anchor},
        blocking=True,
        return_response=True,
        context=context,
    )
    assert repeated == ended
    await hass.config_entries.async_unload(entry.entry_id)


async def test_service_record_target_cannot_cross_point_and_ws_denies_without_side_effect(
    hass, tmp_path, hass_ws_client, hass_read_only_user, hass_read_only_access_token
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await second_point(hass, entry, runtime)
    record = await runtime.async_command(
        "start", {"point_id": "other", "request_id": "foreign"}
    )
    anchor = next(
        p["identity_entity_id"]
        for p in (await runtime.async_snapshot())["points"]
        if p["id"] == "point"
    )
    hass_read_only_user.permissions = PolicyPermissions(
        {"entities": {"entity_ids": {anchor: True}}}, None
    )
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    await client.send_json(
        {
            "id": 1,
            "type": "call_service",
            "domain": "charge_tally",
            "service": "reassign",
            "return_response": True,
            "service_data": {
                "record_id": record["id"],
                "point_id": "point",
                "identity_id": "car",
                "expected_revision": 1,
                "request_id": "foreign",
            },
        }
    )
    result = await client.receive_json()
    assert result["success"] is False
    assert (await runtime.async_query("record", {"record_id": record["id"]}))["record"][
        "identity_id"
    ] == "unassigned"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_public_start_preserves_runtime_helper_readiness_guard(hass, tmp_path):
    entry, runtime = await setup_runtime(hass, tmp_path, periods=["daily"])
    await hass.config_entries.async_remove(
        hass.config_entries.async_entries("utility_meter")[0].entry_id
    )
    await hass.async_block_till_done()
    assert (await runtime.async_snapshot())["points"][0][
        "error"
    ] == "missing_owned_helper"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "charge_tally",
            "start",
            {"point_id": "point", "request_id": "broken"},
            blocking=True,
        )
    assert (await runtime.async_query("records", {}))["total"] == 0
    await hass.config_entries.async_unload(entry.entry_id)


async def test_queued_write_rechecks_permission_after_backup_wait(
    hass, tmp_path, hass_read_only_user, monkeypatch
):
    import asyncio

    entry, runtime = await setup_runtime(hass, tmp_path)
    anchor = (await runtime.async_snapshot())["points"][0]["identity_entity_id"]
    hass_read_only_user.permissions = PolicyPermissions(
        {"entities": {"entity_ids": {anchor: True}}}, None
    )
    await runtime.async_pre_backup()
    entered = asyncio.Event()
    original_wait = runtime._gate.wait

    async def wait():
        entered.set()
        return await original_wait()

    monkeypatch.setattr(runtime._gate, "wait", wait)
    task = asyncio.create_task(
        hass.services.async_call(
            "charge_tally",
            "start",
            {"point_id": "point", "request_id": "queued"},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    )
    await entered.wait()
    hass_read_only_user.permissions = PolicyPermissions(
        {"entities": {"entity_ids": {}}}, None
    )
    runtime.async_post_backup()
    with pytest.raises(Unauthorized):
        await task
    assert (await runtime.async_query("records", {}))["total"] == 0
    await hass.config_entries.async_unload(entry.entry_id)
