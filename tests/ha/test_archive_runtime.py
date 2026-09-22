"""Archive operations preserve worker state and configuration boundaries."""
import asyncio
import sqlite3
import threading

import pytest

from test_currency_options import setup_entry, add_point, add_subentry


async def archived_point(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    await add_point(hass, entry)
    point_id = next(iter(entry.subentries))
    hass.config_entries.async_remove_subentry(entry, point_id)
    await hass.async_block_till_done()
    return entry, point_id


async def test_delete_point_removes_memory_and_checkpoint(hass, tmp_path):
    entry, point_id = await archived_point(hass, tmp_path)
    runtime = entry.runtime_data
    preview = await runtime.async_archive_preview("point", point_id)
    await runtime.async_archive_delete("point", point_id, preview["fingerprint"])
    assert point_id not in runtime._store.states
    state = await runtime._read(runtime._store.ledger.get_checkpoint, "runtime")
    assert point_id not in state
    assert not runtime.snapshot["archived_points"]
    await runtime._apply("snapshot")
    assert await runtime._read(runtime._store.ledger.get_point, point_id) is None
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert point_id not in entry.runtime_data._store.states
    assert not entry.runtime_data.snapshot["archived_points"]


async def test_disabled_configured_identity_cannot_be_archived(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    await add_subentry(hass, entry, "identity", {"name": "Disabled", "enabled": False})
    await hass.async_block_till_done()
    runtime = entry.runtime_data
    identity_id = next(iter(entry.subentries))
    catalog = await runtime.async_archive_catalog()
    assert not catalog["identities"]
    with pytest.raises(ValueError, match="archive_configured"):
        await runtime.async_archive_preview("identity", identity_id)


async def test_archive_waits_for_backup_gate(hass, tmp_path):
    entry, point_id = await archived_point(hass, tmp_path)
    runtime = entry.runtime_data
    preview = await runtime.async_archive_preview("point", point_id)
    await runtime.async_pre_backup()
    task = asyncio.create_task(runtime.async_archive_delete("point", point_id, preview["fingerprint"]))
    await asyncio.sleep(0)
    assert not task.done()
    runtime.async_post_backup()
    await task


@pytest.mark.parametrize("cancel", [True, False])
async def test_prepared_delete_rolls_back_on_cancel_or_config_race(hass, tmp_path, monkeypatch, cancel):
    entry, point_id = await archived_point(hass, tmp_path)
    runtime = entry.runtime_data
    preview = await runtime.async_archive_preview("point", point_id)
    original = runtime._worker
    prepared = asyncio.Event()
    resume = asyncio.Event()

    async def worker(function, *args):
        result = await original(function, *args)
        if function == runtime._store.archive_prepare:
            prepared.set()
            await resume.wait()
        return result

    monkeypatch.setattr(runtime, "_worker", worker)
    task = asyncio.create_task(runtime.async_archive_delete("point", point_id, preview["fingerprint"]))
    await prepared.wait()
    if cancel:
        task.cancel()
    else:
        original_config = runtime._config
        monkeypatch.setattr(runtime, "_config", lambda: ({point_id: {}}, original_config()[1]))
    resume.set()
    with pytest.raises(asyncio.CancelledError if cancel else ValueError):
        await task
    assert await runtime._read(runtime._store.ledger.get_point, point_id) is not None
    assert point_id in runtime._store.states
    assert point_id in await runtime._read(runtime._store.ledger.get_checkpoint, "runtime")


async def identity_fixture(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    for name in ("Old", "Receiver"):
        await add_subentry(hass, entry, "identity", {"name": name, "enabled": True})
    await add_point(hass, entry)
    await hass.async_block_till_done()
    old_id, target_id, point_id = entry.subentries
    hass.config_entries.async_remove_subentry(entry, old_id)
    await hass.async_block_till_done()
    return entry, old_id, target_id, point_id


async def test_identity_remaps_all_selected_states_without_erasing_others(hass, tmp_path):
    entry, old_id, target_id, point_id = await identity_fixture(hass, tmp_path)
    runtime = entry.runtime_data

    def select_archived():
        runtime._store.states[point_id]["selected_identity_id"] = old_id
        runtime._store.states["other_archived"] = {"selected_identity_id": old_id, "reading": "23"}

    await runtime._read(select_archived)
    preview = await runtime.async_archive_preview("identity", old_id, target_id)
    await runtime.async_archive_delete("identity", old_id, preview["fingerprint"], target_id)
    checkpoint = await runtime._read(runtime._store.ledger.get_checkpoint, "runtime")
    assert checkpoint == runtime._store.states
    assert checkpoint[point_id]["selected_identity_id"] == target_id
    assert checkpoint["other_archived"] == {"selected_identity_id": target_id, "reading": "23"}
    assert runtime.snapshot["points"][0]["selected_identity_id"] == target_id


async def test_pending_detector_blocks_identity_delete(hass, tmp_path):
    entry, old_id, target_id, point_id = await identity_fixture(hass, tmp_path)
    runtime = entry.runtime_data
    preview = await runtime.async_archive_preview("identity", old_id, target_id)

    def candidate():
        runtime._store.states[point_id]["detector"] = {
            "state": "pending_start", "candidate": "2026-09-18T00:00:00+00:00", "identity_id": old_id,
        }

    await runtime._read(candidate)
    with pytest.raises(ValueError, match="archive_busy"):
        await runtime.async_archive_delete("identity", old_id, preview["fingerprint"], target_id)
    assert await runtime._read(runtime._store.ledger.get_identity, old_id) is not None


async def test_catalog_rejects_newly_disabled_target_before_config_refresh(hass, tmp_path):
    entry, old_id, target_id, point_id = await identity_fixture(hass, tmp_path)
    runtime = entry.runtime_data
    subentry = entry.subentries[target_id]
    async with runtime._config_lock:
        hass.config_entries.async_update_subentry(entry, subentry, data={**subentry.data, "enabled": False})
        points, identities = runtime._config()
        catalog = await runtime._read(runtime._store.archive_catalog, points, identities)
        assert target_id not in {item["id"] for item in catalog["targets"]}


async def test_real_target_disable_after_prepare_rolls_back(hass, tmp_path, monkeypatch):
    entry, old_id, target_id, point_id = await identity_fixture(hass, tmp_path)
    runtime = entry.runtime_data
    preview = await runtime.async_archive_preview("identity", old_id, target_id)
    original = runtime._worker

    async def worker(function, *args):
        result = await original(function, *args)
        if function == runtime._store.archive_prepare:
            subentry = entry.subentries[target_id]
            hass.config_entries.async_update_subentry(entry, subentry, data={**subentry.data, "enabled": False})
        return result

    monkeypatch.setattr(runtime, "_worker", worker)
    with pytest.raises(ValueError, match="archive_target"):
        await runtime.async_archive_delete("identity", old_id, preview["fingerprint"], target_id)
    assert await runtime._read(runtime._store.ledger.get_identity, old_id) is not None


async def test_active_identity_still_prevents_archive_deletion(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    await add_subentry(hass, entry, "identity", {"name": "Active car", "enabled": True})
    await add_point(hass, entry)
    runtime = entry.runtime_data
    identity_id, point_id = entry.subentries
    await runtime.async_command("select_identity", {"point_id": point_id, "identity_id": identity_id})
    record = await runtime.async_command("start", {"point_id": point_id, "request_id": "active"})
    hass.config_entries.async_remove_subentry(entry, identity_id)
    await hass.async_block_till_done()
    with pytest.raises(ValueError, match="archive_busy"):
        await runtime.async_archive_preview("identity", identity_id, "unassigned")
    with pytest.raises(ValueError, match="archive_busy"):
        await runtime.async_archive_delete("identity", identity_id, "unused", "unassigned")
    assert (await runtime._read(runtime._store.ledger.get_record, record["id"]))["status"] == "active"


async def test_prepare_failure_restores_states_and_database(hass, tmp_path, monkeypatch):
    entry, point_id = await archived_point(hass, tmp_path)
    runtime = entry.runtime_data
    preview = await runtime.async_archive_preview("point", point_id)

    def snapshot(*args):
        raise RuntimeError("Snapshot failed")

    monkeypatch.setattr(runtime._store, "snapshot", snapshot)
    with pytest.raises(RuntimeError, match="Snapshot failed"):
        await runtime.async_archive_delete("point", point_id, preview["fingerprint"])
    assert await runtime._read(runtime._store.ledger.get_point, point_id) is not None
    assert point_id in runtime._store.states
    assert point_id in await runtime._read(runtime._store.ledger.get_checkpoint, "runtime")


async def test_unloaded_runtime_rejects_archive_calls(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    runtime = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(ValueError, match="runtime_unavailable"):
        await runtime.async_archive_catalog()


async def test_archived_point_pending_candidate_does_not_prevent_deletion(hass, tmp_path):
    entry, point_id = await archived_point(hass, tmp_path)
    runtime = entry.runtime_data

    def candidate():
        runtime._store.states[point_id]["detector"] = {
            "state": "pending_start", "candidate": "2026-09-18T00:00:00+00:00", "identity_id": "unassigned",
        }

    await runtime._read(candidate)
    preview = await runtime.async_archive_preview("point", point_id)
    await runtime.async_archive_delete("point", point_id, preview["fingerprint"])
    assert point_id not in runtime._store.states
    assert await runtime._read(runtime._store.ledger.get_point, point_id) is None


async def test_archived_detector_identity_reference_is_cleared_without_losing_state(hass, tmp_path):
    entry, old_id, target_id, point_id = await identity_fixture(hass, tmp_path)
    runtime = entry.runtime_data
    hass.config_entries.async_remove_subentry(entry, point_id)
    await hass.async_block_till_done()

    def candidate():
        runtime._store.states[point_id].update(selected_identity_id=old_id, reading="23", detector={
            "state": "pending_start", "candidate": "2026-09-18T00:00:00+00:00", "identity_id": old_id,
        })
        runtime._store.states["unrelated_archive"] = {"selected_identity_id": "unassigned", "detector": {
            "state": "pending_start", "candidate": "2026-09-18T00:00:00+00:00", "identity_id": target_id,
        }}

    await runtime._read(candidate)
    preview = await runtime.async_archive_preview("identity", old_id, target_id)
    await runtime.async_archive_delete("identity", old_id, preview["fingerprint"], target_id)
    checkpoint = await runtime._read(runtime._store.ledger.get_checkpoint, "runtime")
    assert checkpoint == runtime._store.states
    assert checkpoint[point_id]["detector"] is None
    assert checkpoint[point_id]["reading"] == "23"
    assert checkpoint[point_id]["selected_identity_id"] == target_id
    assert checkpoint["unrelated_archive"]["detector"]["identity_id"] == target_id
    assert await runtime._read(runtime._store.ledger.get_point, point_id) is not None


async def test_commit_failure_rolls_back_and_keeps_connection_usable(hass, tmp_path):
    entry, point_id = await archived_point(hass, tmp_path)
    runtime = entry.runtime_data
    preview = await runtime.async_archive_preview("point", point_id)

    class FailCommitOnce:
        def __init__(self, connection):
            self.connection = connection
            self.fail = True

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, sql, *args):
            if sql == "COMMIT" and self.fail:
                self.fail = False
                raise sqlite3.OperationalError("Injected COMMIT failure")
            return self.connection.execute(sql, *args)

    def inject():
        runtime._store.ledger._db = FailCommitOnce(runtime._store.ledger._db)

    await runtime._read(inject)
    with pytest.raises(sqlite3.OperationalError, match="Injected COMMIT failure"):
        await runtime.async_archive_delete("point", point_id, preview["fingerprint"])
    assert await runtime._read(runtime._store.ledger.get_point, point_id) is not None
    checkpoint = await runtime._read(runtime._store.ledger.get_checkpoint, "runtime")
    assert checkpoint == runtime._store.states
    assert point_id in checkpoint
    await runtime.async_archive_delete("point", point_id, preview["fingerprint"])
    assert await runtime._read(runtime._store.ledger.get_point, point_id) is None


async def test_cancel_after_commit_dispatch_returns_success(hass, tmp_path, monkeypatch):
    entry, point_id = await archived_point(hass, tmp_path)
    runtime = entry.runtime_data
    preview = await runtime.async_archive_preview("point", point_id)
    original = runtime._store.archive_finish
    dispatched = asyncio.Event()
    release = threading.Event()

    def finish(commit):
        if commit:
            hass.loop.call_soon_threadsafe(dispatched.set)
            assert release.wait(10)
        return original(commit)

    monkeypatch.setattr(runtime._store, "archive_finish", finish)
    task = asyncio.create_task(runtime.async_archive_delete("point", point_id, preview["fingerprint"]))
    try:
        await dispatched.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    result = await task
    assert result["id"] == point_id
    assert not runtime.snapshot["archived_points"]
    assert point_id not in await runtime._read(runtime._store.ledger.get_checkpoint, "runtime")
