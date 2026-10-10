"""Managed rules survive interrupted native API writes without losing ownership."""

from copy import deepcopy

import pytest
from homeassistant.components.tag import TAG_DATA
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from test_runtime import setup_runtime


async def setup_manager(hass, tmp_path, **runtime_options):
    entry, runtime = await setup_runtime(hass, tmp_path, **runtime_options)
    assert await async_setup_component(hass, "tag", {})
    await hass.data[TAG_DATA].async_create_item({"tag_id": "tag-a", "name": "Tag"})
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("charge_tally", "scanner")},
        name="Phone",
    )
    manager = runtime.nfc
    draft = {
        "point_id": "point",
        "tag_id": "tag-a",
        "device_bindings": [{"device_id": device.id, "identity_id": "car"}],
        "default_identity_id": "unassigned",
    }
    return entry, runtime, manager, draft


async def create_rule(manager, draft, operation="create"):
    prepared = await manager.async_prepare("create", None, draft, None, operation)
    return await manager.async_confirm(operation, prepared["desired_config"])


async def test_pending_survives_restart_and_confirm_is_idempotent(hass, tmp_path):
    from custom_components.charge_tally.nfc_manager import NfcManager

    entry, runtime, manager, draft = await setup_manager(hass, tmp_path)
    prepared = await manager.async_prepare("create", None, draft, None, "op")
    assert prepared == await manager.async_prepare("create", None, draft, None, "op")
    with pytest.raises(ValueError, match="not_applied"):
        manager.assert_selection(prepared["rule_id"], 1, "point", "car")
    restored = NfcManager(hass, entry, runtime_lock=runtime._lock)
    await restored.async_load()
    assert (await restored.async_list())[0]["pending"] == prepared
    saved = await restored.async_confirm("op", prepared["desired_config"])
    assert saved["automation_id"] == prepared["automation_id"]
    assert saved == await restored.async_confirm("op", prepared["desired_config"])
    restored.assert_selection(saved["rule_id"], 1, "point", "car")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_duplicate_pair_stale_revision_and_changed_retry_are_rejected(
    hass, tmp_path
):
    entry, _, manager, draft = await setup_manager(hass, tmp_path)
    rule = await create_rule(manager, draft)
    with pytest.raises(ValueError, match="duplicate_rule"):
        await manager.async_prepare("create", None, draft, None, "duplicate")
    with pytest.raises(ValueError, match="conflict"):
        await manager.async_prepare("update", rule["rule_id"], draft, 0, "stale")
    changed = {**draft, "default_identity_id": None}
    with pytest.raises(ValueError, match="conflict"):
        await manager.async_prepare("create", None, changed, None, "create")
    prepared = await manager.async_prepare(
        "update", rule["rule_id"], changed, rule["revision"], "update"
    )
    with pytest.raises(ValueError, match="pending"):
        await manager.async_prepare(
            "update", rule["rule_id"], draft, rule["revision"], "second"
        )
    assert prepared["version"] == 2
    await hass.config_entries.async_unload(entry.entry_id)


async def test_failed_store_write_does_not_publish_new_version(
    hass, tmp_path, monkeypatch
):
    entry, _, manager, draft = await setup_manager(hass, tmp_path)
    rule = await create_rule(manager, draft)
    prepared = await manager.async_prepare(
        "update",
        rule["rule_id"],
        {**draft, "default_identity_id": None},
        rule["revision"],
        "update",
    )

    async def fail(_):
        raise OSError("Disk unavailable")

    monkeypatch.setattr(manager.store, "async_save", fail)
    with pytest.raises(OSError):
        await manager.async_confirm("update", prepared["desired_config"])
    manager.assert_selection(rule["rule_id"], 1, "point", "car")
    with pytest.raises(ValueError, match="not_applied"):
        manager.assert_selection(rule["rule_id"], 2, "point", "car")
    assert (await manager.async_list())[0]["pending"] is not None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_external_modification_restore_and_missing_recreate(hass, tmp_path):
    entry, _, manager, draft = await setup_manager(hass, tmp_path)
    rule = await create_rule(manager, draft)
    config = rule["applied"]["automation_config"]
    renamed = {**config, "alias": "My name"}
    assert (await manager.async_inspect(rule["rule_id"], renamed))[
        "config_status"
    ] == "synced"
    changed = {**config, "actions": []}
    assert (await manager.async_inspect(rule["rule_id"], changed))[
        "config_status"
    ] == "external"
    assert (await manager.async_inspect(rule["rule_id"], None))[
        "config_status"
    ] == "missing"
    prepared = await manager.async_prepare(
        "restore", rule["rule_id"], None, rule["revision"], "restore"
    )
    with pytest.raises(ValueError, match="conflict"):
        await manager.async_confirm("restore", changed)
    restored = await manager.async_confirm("restore", prepared["desired_config"])
    recreated = await manager.async_prepare(
        "recreate", rule["rule_id"], None, restored["revision"], "recreate"
    )
    assert recreated["automation_id"] == rule["automation_id"]
    assert recreated["version"] == 3
    await hass.config_entries.async_unload(entry.entry_id)


async def test_delete_blocks_action_before_native_write_and_is_recoverable(
    hass, tmp_path
):
    entry, _, manager, draft = await setup_manager(hass, tmp_path)
    rule = await create_rule(manager, draft)
    await manager.async_prepare(
        "delete", rule["rule_id"], None, rule["revision"], "delete"
    )
    with pytest.raises(ValueError, match="not_applied"):
        manager.assert_selection(rule["rule_id"], 1, "point", "car")
    with pytest.raises(ValueError, match="conflict"):
        await manager.async_confirm("delete", rule["applied"]["automation_config"])
    assert await manager.async_confirm("delete", None) is None
    assert await manager.async_confirm("delete", None) is None
    assert await manager.async_list() == []
    await hass.config_entries.async_unload(entry.entry_id)


async def test_cancel_only_unwritten_changes_and_invalid_reference_never_falls_back(
    hass, tmp_path
):
    entry, _, manager, draft = await setup_manager(hass, tmp_path)
    rule = await create_rule(manager, draft)
    prepared = await manager.async_prepare(
        "update",
        rule["rule_id"],
        {**draft, "default_identity_id": None},
        rule["revision"],
        "update",
    )
    with pytest.raises(ValueError, match="conflict"):
        await manager.async_cancel("update", prepared["desired_config"])
    await manager.async_cancel("update", rule["applied"]["automation_config"])
    sub = entry.subentries["car"]
    data = deepcopy(dict(sub.data))
    data["enabled"] = False
    hass.config_entries.async_update_subentry(entry, sub, data=data)
    with pytest.raises(ValueError, match="invalid_reference"):
        manager.assert_selection(rule["rule_id"], 1, "point", "unassigned")
    await hass.data[TAG_DATA].async_delete_item("tag-a")
    assert (
        await manager.async_inspect(
            rule["rule_id"], rule["applied"]["automation_config"]
        )
    )["config_status"] == "invalid"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_explicit_restore_recovers_pending_conflict_without_reusing_version(
    hass, tmp_path
):
    entry, _, manager, draft = await setup_manager(hass, tmp_path)
    rule = await create_rule(manager, draft)
    old_pending = await manager.async_prepare(
        "update",
        rule["rule_id"],
        {**draft, "default_identity_id": None},
        rule["revision"],
        "update",
    )
    current = (await manager.async_list())[0]
    prepared = await manager.async_prepare(
        "restore", rule["rule_id"], None, current["revision"], "restore"
    )
    assert prepared["version"] == 3
    assert prepared["draft"] == draft
    with pytest.raises(ValueError, match="conflict"):
        await manager.async_confirm("update", old_pending["desired_config"])
    restored = await manager.async_confirm("restore", prepared["desired_config"])
    manager.assert_selection(rule["rule_id"], 3, "point", "car")
    assert restored["pending"] is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_generated_copy_uses_ha_language_and_registered_names(hass, tmp_path):
    hass.config.language = "zh-Hans"
    entry, _, manager, draft = await setup_manager(hass, tmp_path)
    prepared = await manager.async_prepare("create", None, draft, None, "create")
    assert (
        prepared["desired_config"]["alias"]
        == "[Charge Tally 托管] Garage · Tag · 身份切换"
    )
    assert "请勿直接修改" in prepared["desired_config"]["description"]
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("kind", ["create", "update"])
async def test_written_change_can_be_confirmed_after_device_removal(
    hass, tmp_path, kind
):
    entry, _, manager, draft = await setup_manager(hass, tmp_path)
    rule = await create_rule(manager, draft) if kind == "update" else None
    prepared = await manager.async_prepare(
        kind,
        rule["rule_id"] if rule else None,
        draft,
        rule["revision"] if rule else None,
        "write",
    )
    dr.async_get(hass).async_remove_device(draft["device_bindings"][0]["device_id"])
    saved = await manager.async_confirm("write", prepared["desired_config"])
    assert saved["pending"] is None
    assert (await manager.async_inspect(saved["rule_id"], prepared["desired_config"]))[
        "config_status"
    ] == "invalid"
    with pytest.raises(ValueError, match="invalid_reference"):
        manager.assert_selection(
            saved["rule_id"], saved["applied"]["version"], "point", "unassigned"
        )
    repaired = await manager.async_prepare(
        "update",
        saved["rule_id"],
        {**draft, "device_bindings": []},
        saved["revision"],
        "repair",
    )
    await manager.async_confirm("repair", repaired["desired_config"])
    manager.assert_selection(
        saved["rule_id"], repaired["version"], "point", "unassigned"
    )
    await hass.config_entries.async_unload(entry.entry_id)


async def test_pending_delete_can_be_cancelled_without_touching_external_config(
    hass, tmp_path
):
    entry, _, manager, draft = await setup_manager(hass, tmp_path)
    rule = await create_rule(manager, draft)
    await manager.async_prepare(
        "delete", rule["rule_id"], None, rule["revision"], "delete"
    )
    with pytest.raises(ValueError, match="conflict"):
        await manager.async_cancel("delete", None)
    changed = {**rule["applied"]["automation_config"], "actions": []}
    restored = await manager.async_cancel("delete", changed)
    assert restored["pending"] is None
    assert restored["deleting"] is False
    assert (await manager.async_inspect(rule["rule_id"], changed))[
        "config_status"
    ] == "external"
    with pytest.raises(ValueError, match="conflict"):
        await manager.async_confirm("delete", None)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_external_config_can_be_restored_with_repaired_references(hass, tmp_path):
    entry, _, manager, draft = await setup_manager(hass, tmp_path)
    rule = await create_rule(manager, draft)
    dr.async_get(hass).async_remove_device(draft["device_bindings"][0]["device_id"])
    changed = {**rule["applied"]["automation_config"], "actions": []}
    assert (await manager.async_inspect(rule["rule_id"], changed))[
        "config_status"
    ] == "external"
    repaired = await manager.async_prepare(
        "restore",
        rule["rule_id"],
        {**draft, "device_bindings": []},
        rule["revision"],
        "repair",
    )
    assert repaired["automation_id"] == rule["automation_id"]
    assert repaired["version"] == 2
    await manager.async_confirm("repair", repaired["desired_config"])
    manager.assert_selection(rule["rule_id"], 2, "point", "unassigned")
    await hass.config_entries.async_unload(entry.entry_id)
