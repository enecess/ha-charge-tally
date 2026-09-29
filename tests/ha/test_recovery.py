"""Lifecycle failures retain accounting, and backup files are consistent."""

import asyncio
import shutil
from decimal import Decimal

import pytest
from test_runtime import ENERGY, POWER, setup_runtime, tick


async def test_missing_helper_keeps_runtime_end_and_explicit_repair(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(hass, tmp_path, periods=["daily"])
    record = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "r1"}
    )
    helper = hass.config_entries.async_entries("utility_meter")[0]
    await hass.config_entries.async_remove(helper.entry_id)
    await runtime.async_refresh_config()
    assert (await runtime.async_snapshot())["points"][0]["error"]
    await tick(hass, freezer, 30)
    result = await runtime.async_command(
        "end", {"record_id": record["id"], "request_id": "e1"}
    )
    assert result["status"] == "ended"
    assert not hass.config_entries.async_entries("utility_meter")
    await runtime.async_command("repair", {"point_id": "point"})
    assert len(hass.config_entries.async_entries("utility_meter")) == 1
    assert (await runtime.async_snapshot())["points"][0]["error"] is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_backup_pauses_events_and_restores_committed_checkpoint(
    hass, tmp_path, freezer
):
    from custom_components.charge_tally.backup import (
        async_post_backup,
        async_pre_backup,
    )
    from custom_components.charge_tally.ledger import Ledger

    entry, runtime = await setup_runtime(hass, tmp_path)
    await runtime.async_command("start", {"point_id": "point", "request_id": "r1"})
    await tick(hass, freezer, 30)
    hass.states.async_set("sensor.energy", "100.060", ENERGY)
    await hass.async_block_till_done()
    await async_pre_backup(hass)
    paused = hass.async_create_task(
        runtime.async_command(
            "select_identity", {"point_id": "point", "identity_id": "car"}
        )
    )
    await asyncio.sleep(0)
    assert not paused.done()
    backup = tmp_path / "charge_tally" / "ledger.backup.sqlite3"
    assert backup.exists()
    await async_post_backup(hass)
    await paused
    assert await hass.config_entries.async_unload(entry.entry_id)
    ledger = Ledger(str(backup))
    assert Decimal(
        ledger.get_checkpoint("runtime")["point"]["normalized_energy_kwh"]
    ) == Decimal(".060")
    assert (
        ledger.get_checkpoint("runtime")["point"]["selected_identity_id"]
        == "unassigned"
    )
    assert Decimal(ledger.list_records()[0]["energy_kwh"]) == Decimal(".060")
    ledger.close()
    await hass.async_add_executor_job(
        shutil.copyfile, backup, tmp_path / "charge_tally" / "ledger.sqlite3"
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    restored = (await entry.runtime_data.async_snapshot())["points"][0]
    assert Decimal(restored["normalized_energy_kwh"]) == Decimal(".060")
    assert restored["selected_identity_id"] == "unassigned"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await async_post_backup(hass)


async def test_none_interrupts_candidate_and_restart_does_not_count_downtime(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(
        hass,
        tmp_path,
        detection={
            "enabled": True,
            "start_w": "500",
            "end_w": "100",
            "start_seconds": 30,
            "end_seconds": 60,
        },
    )
    hass.states.async_set("sensor.power", "1000", POWER)
    await hass.async_block_till_done()
    await tick(hass, freezer, 20)
    hass.states.async_set("sensor.power", "unavailable", POWER)
    await hass.async_block_till_done()
    await tick(hass, freezer, 20)
    assert not (await runtime.async_snapshot())["records"]
    hass.states.async_set("sensor.power", "1000", POWER)
    await hass.async_block_till_done()
    await tick(hass, freezer, 20)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await tick(hass, freezer, 100)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert not (await entry.runtime_data.async_snapshot())["records"]
    await tick(hass, freezer, 31)
    assert len((await entry.runtime_data.async_snapshot())["records"]) == 1
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_deleted_point_and_identity_keep_history(hass, tmp_path, freezer):
    entry, runtime = await setup_runtime(hass, tmp_path)
    record = await runtime.async_command(
        "start", {"point_id": "point", "identity_id": "car", "request_id": "r1"}
    )
    await tick(hass, freezer, 10)
    await runtime.async_command("end", {"record_id": record["id"], "request_id": "e1"})
    hass.config_entries.async_remove_subentry(entry, "car")
    hass.config_entries.async_remove_subentry(entry, "point")
    await hass.async_block_till_done()
    snapshot = await runtime.async_snapshot()
    assert snapshot["points"] == []
    assert snapshot["records"][0]["identity_id"] == "car"
    assert (
        next(i for i in snapshot["identities"] if i["id"] == "car")["active"] is False
    )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_owned_helper_issue_has_explicit_real_repairs_flow(hass, tmp_path):
    from homeassistant.helpers import issue_registry as ir

    from custom_components.charge_tally.repairs import async_create_fix_flow

    entry, runtime = await setup_runtime(hass, tmp_path, periods=["daily"])
    await hass.config_entries.async_remove(
        hass.config_entries.async_entries("utility_meter")[0].entry_id
    )
    await runtime.async_refresh_config()
    issue_id = entry.entry_id + ":point"
    issue = ir.async_get(hass).async_get_issue("charge_tally", issue_id)
    assert issue is not None
    flow = await async_create_fix_flow(hass, issue_id, issue.data)
    flow.hass = hass
    assert (await flow.async_step_init({"issue_id": issue_id}))["type"] == "form"
    assert not hass.config_entries.async_entries("utility_meter")
    assert (await flow.async_step_confirm({}))["type"] == "create_entry"
    assert len(hass.config_entries.async_entries("utility_meter")) == 1
    assert ir.async_get(hass).async_get_issue("charge_tally", issue_id) is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_deleting_helper_immediately_surfaces_repair_without_config_edit(
    hass, tmp_path
):
    entry, runtime = await setup_runtime(hass, tmp_path, periods=["daily"])
    await hass.config_entries.async_remove(
        hass.config_entries.async_entries("utility_meter")[0].entry_id
    )
    await hass.async_block_till_done()
    assert (await runtime.async_snapshot())["points"][0][
        "error"
    ] == "missing_owned_helper"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_removed_point_retains_active_record_for_explicit_end_and_history_edit(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    record = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "r1"}
    )
    await tick(hass, freezer, 30)
    hass.config_entries.async_remove_subentry(entry, "point")
    await hass.async_block_till_done()
    snapshot = await runtime.async_snapshot()
    assert snapshot["archived_points"][0]["id"] == "point"
    assert snapshot["archived_points"][0]["identity_entity_id"] is None
    ended = await runtime.async_command(
        "end", {"record_id": record["id"], "request_id": "e1"}
    )
    assert ended["status"] == "ended"
    detail = await runtime.async_query(
        "record", {"record_id": record["id"]}, point_ids=["point"]
    )
    assert detail["point"]["active"] is False
    preview = await runtime.async_command(
        "preview",
        {
            "record_id": record["id"],
            "expected_revision": ended["revision"],
            "start": ended["start"],
            "end": ended["end"],
            "energy_kwh": "1",
        },
    )
    assert Decimal(preview["record"]["energy_kwh"]) == 1
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_home_assistant_stop_closes_worker_and_cancels_pending_timers(
    hass, tmp_path
):
    entry, runtime = await setup_runtime(
        hass,
        tmp_path,
        detection={
            "enabled": True,
            "start_w": "500",
            "end_w": "100",
            "start_seconds": 30,
            "end_seconds": 60,
        },
    )
    hass.states.async_set("sensor.power", "1000", POWER)
    await hass.async_block_till_done()
    await hass.async_stop()
    assert runtime._closed
    assert not runtime._timers
    with pytest.raises(ValueError, match="closed"):
        await runtime.async_command(
            "select_identity", {"point_id": "point", "identity_id": "car"}
        )


async def test_removing_point_clears_only_its_own_stale_helper_issue(hass, tmp_path):
    from homeassistant.helpers import issue_registry as ir

    entry, runtime = await setup_runtime(hass, tmp_path, periods=["daily"])
    await hass.config_entries.async_remove(
        hass.config_entries.async_entries("utility_meter")[0].entry_id
    )
    await hass.async_block_till_done()
    issue_id = entry.entry_id + ":point"
    registry = ir.async_get(hass)
    assert registry.async_get_issue("charge_tally", issue_id) is not None
    ir.async_create_issue(
        hass,
        "charge_tally",
        "other_issue",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="other",
    )
    hass.config_entries.async_remove_subentry(entry, "point")
    await hass.async_block_till_done()
    assert registry.async_get_issue("charge_tally", issue_id) is None
    assert registry.async_get_issue("charge_tally", "other_issue") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
