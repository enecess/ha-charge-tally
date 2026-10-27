"""Whole-entry removal starts fresh without changing reload or subentry semantics."""

import asyncio
import threading
from pathlib import Path

import pytest
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from test_runtime import setup_runtime

from custom_components.charge_tally.runtime_store import RuntimeStore


async def new_flow(hass):
    return await hass.config_entries.flow.async_init(
        "charge_tally", context={"source": "user"}
    )


async def submit(hass, flow, currency):
    return await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"currency": currency}
    )


@pytest.mark.parametrize("unload_first", [False, True])
async def test_remove_entry_clears_owned_data_and_readd_uses_new_currency(
    hass, tmp_path, unload_first
):
    entry, runtime = await setup_runtime(hass, tmp_path, periods=["daily"])
    await runtime.async_command("start", {"point_id": "point", "request_id": "old"})
    await runtime.nfc.store.async_save(runtime.nfc._data)
    await runtime.async_pre_backup()
    runtime.async_post_backup()
    directory = tmp_path / "charge_tally"
    unrelated = directory / "user-notes.txt"
    unrelated.write_text("keep", encoding="utf-8")
    helper_ids = {
        helper.entry_id for helper in hass.config_entries.async_entries("utility_meter")
    }
    assert helper_ids
    if unload_first:
        assert await hass.config_entries.async_unload(entry.entry_id)
        for name in ("ledger.sqlite3", "ledger.backup.sqlite3"):
            for suffix in ("-wal", "-shm", "-journal"):
                (directory / (name + suffix)).write_bytes(b"stale")
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert not (directory / "ledger.sqlite3").exists()
    assert not (directory / "ledger.backup.sqlite3").exists()
    assert sorted(item.name for item in directory.iterdir()) == ["user-notes.txt"]
    assert not Path(runtime.nfc.store.path).exists()
    assert not Path(runtime._helpers._store.path).exists()
    assert all(hass.config_entries.async_get_entry(id_) is None for id_ in helper_ids)
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert hass.states.get("sensor.energy") is not None
    result = await submit(hass, await new_flow(hass), "USD")
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    fresh = result["result"].runtime_data
    assert fresh.snapshot["currency"] == "USD"
    assert fresh.snapshot["records"] == []
    assert fresh.snapshot["archived_points"] == []
    assert [item["id"] for item in fresh.snapshot["identities"]] == ["unassigned"]


@pytest.mark.parametrize("corrupt", [False, True])
async def test_orphan_ledger_is_reset_only_after_valid_submission(
    hass, tmp_path, corrupt
):
    path = tmp_path / "charge_tally" / "ledger.sqlite3"

    def seed():
        store = RuntimeStore(str(path), "CNY", "UTC")
        store.ledger.put_point({"id": "old", "name": "Old", "active": False})
        store.ledger.backup(str(path.with_name("ledger.backup.sqlite3")))
        store.ledger.close()
        if corrupt:
            path.write_bytes(b"old damaged ledger")

    await hass.async_add_executor_job(seed)
    before = path.read_bytes()
    flow = await new_flow(hass)
    assert flow["type"] == FlowResultType.FORM
    assert path.read_bytes() == before
    with pytest.raises(InvalidData):
        await submit(hass, flow, "invalid")
    assert path.read_bytes() == before
    result = await submit(hass, flow, "USD")
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert result["result"].runtime_data.snapshot["currency"] == "USD"
    assert result["result"].runtime_data.snapshot["archived_points"] == []
    assert not path.with_name("ledger.backup.sqlite3").exists()


async def test_failed_orphan_cleanup_does_not_create_entry(hass, tmp_path, monkeypatch):
    path = tmp_path / "charge_tally" / "ledger.sqlite3"
    path.parent.mkdir()
    path.write_bytes(b"old ledger")
    original = Path.unlink

    def fail(target, *args, **kwargs):
        if target == path:
            raise PermissionError("in use")
        return original(target, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail)
    result = await submit(hass, await new_flow(hass), "USD")
    assert result["errors"] == {"base": "cleanup_failed"}
    assert not hass.config_entries.async_entries("charge_tally")
    assert path.read_bytes() == b"old ledger"
    monkeypatch.setattr(Path, "unlink", original)
    result = await submit(hass, result, "USD")
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_reload_and_duplicate_flow_keep_existing_ledger(hass, tmp_path):
    entry, runtime = await setup_runtime(hass, tmp_path)
    record = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "keep"}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    flow = await new_flow(hass)
    assert flow["reason"] == "single_instance_allowed"
    assert entry.runtime_data.snapshot["records"][0]["id"] == record["id"]
    assert entry.runtime_data.snapshot["currency"] == "CNY"


async def test_entry_removal_does_not_delete_helper_with_changed_owner(hass, tmp_path):
    entry, runtime = await setup_runtime(hass, tmp_path, periods=["daily"])
    helper = hass.config_entries.async_entries("utility_meter")[0]
    hass.config_entries.async_update_entry(helper, unique_id="another-owner")
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.config_entries.async_get_entry(helper.entry_id) is helper
    assert not Path(runtime.path).exists()


async def test_cancelled_cleanup_drains_worker_before_releasing_creation(
    hass, tmp_path, monkeypatch
):
    from custom_components.charge_tally import cleanup

    started = asyncio.Event()
    release = threading.Event()
    original = cleanup.reset_ledger_files

    def slow_reset(path):
        hass.loop.call_soon_threadsafe(started.set)
        assert release.wait(10)
        original(path)

    monkeypatch.setattr(cleanup, "reset_ledger_files", slow_reset)
    task = asyncio.create_task(cleanup.async_prepare_new_ledger(hass))
    try:
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_remove_after_failed_unload_closes_worker_and_clears_data(
    hass, tmp_path, monkeypatch
):
    entry, runtime = await setup_runtime(hass, tmp_path)

    async def failed_unload(*args):
        return False

    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", failed_unload)
    result = await hass.config_entries.async_remove(entry.entry_id)
    assert result["require_restart"]
    assert runtime._closed
    assert not Path(runtime.path).exists()
    assert entry.entry_id not in hass.data.get("charge_tally", {})
