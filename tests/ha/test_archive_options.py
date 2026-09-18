"""Native archive management flows operate on real persisted records."""
from datetime import timedelta
from decimal import Decimal

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util

from test_currency_options import add_point, add_subentry, open_currency, setup_entry


async def archive_flow(hass, entry, kind):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.MENU
    assert set(result["menu_options"]) == {"currency", "archive"}
    for step in ("archive", "archive_points" if kind == "point" else "archive_identities"):
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})
    return result


async def choose(hass, result, data):
    return await hass.config_entries.options.async_configure(result["flow_id"], data)


async def record(hass, entry, identity_id="unassigned"):
    runtime = entry.runtime_data
    end = dt_util.utcnow() - timedelta(minutes=1)
    preview = await runtime.async_command("preview", {
        "point_id": next(sub.subentry_id for sub in entry.subentries.values() if sub.subentry_type == "point"),
        "identity_id": identity_id, "start": (end - timedelta(hours=1)).isoformat(),
        "end": end.isoformat(), "energy_kwh": "10", "cost": "12.34",
    })
    return await runtime.async_command("commit_preview", {"token": preview["token"], "request_id": "history"})


async def archive(hass, entry, object_id):
    hass.config_entries.async_remove_subentry(entry, object_id)
    await hass.async_block_till_done()


async def test_archive_menu_excludes_current_points_disabled_identities_and_builtin(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    await add_point(hass, entry)
    await add_subentry(hass, entry, "identity", {"name": "Disabled", "enabled": False})
    await hass.async_block_till_done()
    result = await archive_flow(hass, entry, "identity")
    assert result["step_id"] == "archive_empty"
    result = await choose(hass, result, {})
    assert result["type"] == FlowResultType.MENU
    result = await choose(hass, result, {"next_step_id": "archive"})
    result = await choose(hass, result, {"next_step_id": "archive_points"})
    assert result["step_id"] == "archive_empty"


async def test_archived_point_requires_confirmation_and_disappears_after_reload(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    await add_point(hass, entry)
    saved = await record(hass, entry)
    point_id = saved["point_id"]
    await archive(hass, entry, point_id)
    result = await archive_flow(hass, entry, "point")
    assert result["step_id"] == "archive_select"
    result = await choose(hass, result, {"object_id": point_id})
    assert result["step_id"] == "archive_confirm"
    details = result["description_placeholders"]
    assert details["records"] == "1"
    assert Decimal(details["cost"]) == Decimal("12.34")
    result = await choose(hass, result, {"confirm": False})
    assert result["errors"] == {"base": "confirm_required"}
    assert (await entry.runtime_data.async_query("record", {"record_id": saved["id"]}))["record"] == saved
    result = await choose(hass, result, {"confirm": True})
    assert result["step_id"] == "archive_done"
    assert result["description_placeholders"]["deleted"] == "1"
    assert (await choose(hass, result, {}))["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.runtime_data.snapshot["archived_points"] == []
    assert entry.runtime_data.snapshot["records"] == []
    assert await entry.runtime_data.async_currency_change_allowed()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.snapshot["archived_points"] == []
    assert entry.runtime_data.snapshot["records"] == []
    assert await entry.runtime_data.async_currency_change_allowed()
    result = await open_currency(hass, entry)
    assert result["step_id"] == "currency"
    result = await choose(hass, result, {"currency": "USD"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.data["currency"] == "USD"
    assert entry.runtime_data.snapshot["currency"] == "USD"


async def test_archived_identity_transfers_records_without_repricing(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    await add_point(hass, entry)
    await add_subentry(hass, entry, "identity", {"name": "Old car", "enabled": True})
    source_id = next(sub.subentry_id for sub in entry.subentries.values() if sub.subentry_type == "identity")
    saved = await record(hass, entry, source_id)
    before = await entry.runtime_data.async_query("record", {"record_id": saved["id"]})
    await archive(hass, entry, source_id)
    result = await archive_flow(hass, entry, "identity")
    result = await choose(hass, result, {"object_id": source_id})
    assert result["step_id"] == "archive_target"
    result = await choose(hass, result, {"target_identity_id": "unassigned"})
    assert result["step_id"] == "archive_confirm"
    result = await choose(hass, result, {"confirm": True})
    assert result["step_id"] == "archive_done"
    assert result["description_placeholders"]["transferred"] == "1"
    after = await entry.runtime_data.async_query("record", {"record_id": saved["id"]})
    assert after["record"]["identity_id"] == "unassigned"
    assert after["record"]["known_cost"] == before["record"]["known_cost"]
    assert Decimal(after["record"]["known_cost"]) == Decimal("12.34")
    assert after["segments"] == before["segments"]
    assert after["revisions"][0]["record"]["identity_name"] == "Old car"
    assert source_id not in {item["id"] for item in entry.runtime_data.snapshot["identities"]}


async def test_delete_unused_identity_keeps_unused_currency_editable(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    await add_subentry(hass, entry, "identity", {"name": "Unused", "enabled": True})
    source_id = next(iter(entry.subentries))
    await archive(hass, entry, source_id)
    result = await archive_flow(hass, entry, "identity")
    result = await choose(hass, result, {"object_id": source_id})
    assert result["step_id"] == "archive_confirm"
    result = await choose(hass, result, {"confirm": True})
    assert result["step_id"] == "archive_done"
    assert await entry.runtime_data.async_currency_change_allowed()


async def test_archive_confirmation_rejects_changed_record(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    await add_point(hass, entry)
    saved = await record(hass, entry)
    await archive(hass, entry, saved["point_id"])
    result = await archive_flow(hass, entry, "point")
    result = await choose(hass, result, {"object_id": saved["point_id"]})
    await entry.runtime_data.async_command("void", {"record_id": saved["id"], "expected_revision": saved["revision"]})
    result = await choose(hass, result, {"confirm": True})
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "archive_stale"
    assert (await entry.runtime_data.async_query("record", {"record_id": saved["id"]}))["record"]["status"] == "void"
