"""Public APIs must enforce point scope before exposing ledger data."""
import asyncio
import pytest
from homeassistant.auth.permissions import PolicyPermissions
from homeassistant.helpers import entity_registry as er
from test_runtime import setup_runtime
from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers.dispatcher import async_dispatcher_send


async def second_point(hass, entry, runtime):
    data = dict(entry.subentries["point"].data)
    data["name"] = "Other garage"
    hass.config_entries.async_add_subentry(entry, ConfigSubentry(data=data, subentry_type="point", title="Other garage", unique_id=None, subentry_id="other"))
    await runtime.async_refresh_config()
    await hass.async_block_till_done()


async def test_scope_precedes_summary_count_pagination_and_record_writes(hass, tmp_path, hass_ws_client, hass_read_only_access_token, hass_read_only_user):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await second_point(hass, entry, runtime)
    own = await runtime.async_command("start", {"point_id": "point", "request_id": "own"})
    foreign = await runtime.async_command("start", {"point_id": "other", "request_id": "foreign"})
    anchor = next(p["identity_entity_id"] for p in (await runtime.async_snapshot())["points"] if p["id"] == "point")
    hass_read_only_user.permissions = PolicyPermissions({"entities": {"entity_ids": {anchor: True}}}, None)
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    messages = [
        {"type": "charge_tally/snapshot"},
        {"type": "charge_tally/records", "limit": 1},
        {"type": "charge_tally/query", "start": "2020-01-01T00:00:00Z", "end": "2099-01-01T00:00:00Z"},
        {"type": "charge_tally/reassign", "record_id": foreign["id"], "identity_id": "car", "expected_revision": 1, "request_id": "bad"},
        {"type": "charge_tally/records", "record_id": foreign["id"]},
        {"type": "charge_tally/records", "record_id": own["id"]},
    ]
    results = []
    for index, message in enumerate(messages, 1):
        await client.send_json({"id": index, **message})
        results.append(await client.receive_json())
    assert [p["id"] for p in results[0]["result"]["points"]] == ["point"]
    assert results[0]["result"]["summary"]["active_count"] == 1
    assert results[1]["result"]["total"] == 1
    assert results[1]["result"]["records"][0]["id"] == own["id"]
    assert results[2]["result"]["active_count"] == 1
    assert results[3]["error"]["code"] == "unauthorized"
    assert results[4]["error"]["code"] == "unauthorized"
    assert results[5]["result"]["record"]["id"] == own["id"]
    assert "segments" in results[5]["result"]
    assert (await runtime.async_query("record", {"record_id": foreign["id"]}))["record"]["identity_id"] == "unassigned"
    other_user = await hass.auth.async_create_user("Other point user", group_ids=[])
    other_anchor = next(p["identity_entity_id"] for p in (await runtime.async_snapshot())["points"] if p["id"] == "other")
    other_user.permissions = PolicyPermissions({"entities": {"entity_ids": {other_anchor: True}}}, None)
    token = hass.auth.async_create_access_token(await hass.auth.async_create_refresh_token(other_user, client_id="http://localhost/"))
    other_client = await hass_ws_client(hass, access_token=token)
    await other_client.send_json({"id": 1, "type": "charge_tally/records"})
    other_records = (await other_client.receive_json())["result"]
    assert other_records["total"] == 1
    assert other_records["records"][0]["id"] == foreign["id"]
    await other_client.send_json({"id": 2, "type": "charge_tally/void", "record_id": own["id"], "expected_revision": 1, "request_id": "foreign-void"})
    assert (await other_client.receive_json())["error"]["code"] == "unauthorized"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_preview_commit_idempotence_and_cross_user_token(hass, tmp_path, hass_ws_client, hass_read_only_access_token, hass_read_only_user, hass_admin_user):
    entry, runtime = await setup_runtime(hass, tmp_path)
    anchor = (await runtime.async_snapshot())["points"][0]["identity_entity_id"]
    hass_read_only_user.permissions = PolicyPermissions({"entities": {"entity_ids": {anchor: True}}}, None)
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    admin = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "charge_tally/preview", "point_id": "point", "identity_id": "car",
        "start": "2025-01-01T00:00:00Z", "end": "2025-01-01T01:00:00Z", "energy_kwh": "2", "cost": "-3"})
    preview = (await client.receive_json())["result"]
    assert "basis_version" not in preview
    await admin.send_json({"id": 1, "type": "charge_tally/commit", "token": preview["token"], "request_id": "stolen"})
    assert (await admin.receive_json())["error"]["code"] == "unauthorized"
    results = []
    for msg_id in (2, 3):
        await client.send_json({"id": msg_id, "type": "charge_tally/commit", "token": preview["token"], "request_id": "commit"})
        results.append(await client.receive_json())
    assert results[0]["success"] is True
    assert results[0]["result"] == results[1]["result"]
    assert results[0]["result"]["known_cost"] == "-3"
    assert (await runtime.async_query("records", {}))["total"] == 1
    hass_read_only_user.permissions = PolicyPermissions({"entities": {"entity_ids": {}}}, None)
    await client.send_json({"id": 4, "type": "charge_tally/commit", "token": preview["token"], "request_id": "commit"})
    assert (await client.receive_json())["error"]["code"] == "unauthorized"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_subscription_reauthorizes_and_standard_cancel_is_idempotent(hass, tmp_path, hass_ws_client, hass_read_only_access_token, hass_read_only_user):
    entry, runtime = await setup_runtime(hass, tmp_path)
    anchor = (await runtime.async_snapshot())["points"][0]["identity_entity_id"]
    hass_read_only_user.permissions = PolicyPermissions({"entities": {"entity_ids": {anchor: True}}}, None)
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    await client.send_json({"id": 1, "type": "charge_tally/subscribe"})
    assert (await client.receive_json())["success"] is True
    assert (await client.receive_json())["event"]["points"][0]["id"] == "point"
    hass_read_only_user.permissions = PolicyPermissions({"entities": {"entity_ids": {}}}, None)
    async_dispatcher_send(hass, runtime.update_signal)
    event = (await client.receive_json())["event"]
    assert event["points"] == []
    assert "revision" not in event
    assert event["generation"] == 2
    await client.send_json({"id": 2, "type": "unsubscribe_events", "subscription": 1})
    assert (await client.receive_json())["success"] is True
    await hass.config_entries.async_unload(entry.entry_id)
    await client.send_json({"id": 3, "type": "ping"})
    assert (await client.receive_json())["type"] == "pong"


async def test_history_missing_coverage_edit_stale_overlap_and_void(hass, tmp_path, hass_ws_client):
    entry, runtime = await setup_runtime(hass, tmp_path)
    client = await hass_ws_client(hass)
    msg_id = 0
    async def request(command, **payload):
        nonlocal msg_id
        msg_id += 1
        await client.send_json({"id": msg_id, "type": "charge_tally/" + command, **payload})
        return await client.receive_json()
    base = {"point_id": "point", "identity_id": "car", "start": "2025-01-01T00:00:00Z", "end": "2025-01-01T01:00:00Z"}
    missing = (await request("preview", **base))["result"]
    assert "missing_energy" in missing["record"]["quality"]
    assert missing["record"]["cost_complete"] is False
    assert (await runtime.async_query("records", {}))["total"] == 0
    manual = (await request("preview", **base, energy_kwh="2", cost="4"))["result"]
    record = (await request("commit", token=manual["token"], request_id="create"))["result"]
    edit = (await request("preview", record_id=record["id"], expected_revision=1, note="Changed"))["result"]
    moved = await request("reassign", record_id=record["id"], identity_id="unassigned", expected_revision=1, request_id="move")
    assert moved["result"]["revision"] == 2
    assert (await request("reassign", record_id=record["id"], identity_id="unassigned", expected_revision=1, request_id="move"))["result"] == moved["result"]
    stale = await request("commit", token=edit["token"], request_id="stale", expected_revision=1)
    assert stale["error"]["code"] == "stale_preview"
    overlap = (await request("preview", **base, energy_kwh="3"))["result"]
    assert overlap["overlaps"] == [record["id"]]
    assert (await request("commit", token=overlap["token"], request_id="overlap"))["error"]["code"] == "overlap"
    edit = (await request("preview", record_id=record["id"], expected_revision=2,
        start="2025-01-01T00:10:00Z", end="2025-01-01T00:50:00Z", energy_kwh="5", cost="6"))["result"]
    saved = (await request("commit", token=edit["token"], request_id="edit", expected_revision=2))["result"]
    assert saved["energy_kwh"] == "5"
    assert saved["known_cost"] == "6"
    voided = await request("void", record_id=record["id"], expected_revision=3, request_id="void")
    assert voided["success"] is True
    assert (await request("records"))["result"]["total"] == 0
    detail = (await request("records", record_id=record["id"]))["result"]
    assert len(detail["revisions"]) == 4
    await hass.config_entries.async_unload(entry.entry_id)


async def test_missing_anchor_denies_history_after_reload_and_admin_can_read(hass, tmp_path, hass_ws_client, hass_read_only_access_token, hass_read_only_user):
    entry, runtime = await setup_runtime(hass, tmp_path)
    record = await runtime.async_command("start", {"point_id": "point", "request_id": "live"})
    hass_read_only_user.permissions = PolicyPermissions({"entities": {"all": True}}, None)
    hass.config_entries.async_remove_subentry(entry, "point")
    await runtime.async_refresh_config()
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    await client.send_json({"id": 1, "type": "charge_tally/records", "record_id": record["id"]})
    assert (await client.receive_json())["error"]["code"] == "unauthorized"
    admin = await hass_ws_client(hass)
    await admin.send_json({"id": 1, "type": "charge_tally/records", "record_id": record["id"]})
    assert (await admin.receive_json())["result"]["point"]["active"] is False
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("change", [{"energy_kwh": "NaN"}, {"cost": "Infinity"}, {"energy_kwh": "-1"},
    {"start": "2025-01-01"}, {"start": "2025-01-02T00:00:00Z"}, {"end": "2999-01-01T01:00:00Z"}])
async def test_invalid_preview_never_creates_records(hass, tmp_path, hass_ws_client, change):
    entry, runtime = await setup_runtime(hass, tmp_path)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "charge_tally/preview", "point_id": "point", "identity_id": "car",
        "start": "2025-01-01T00:00:00Z", "end": "2025-01-01T01:00:00Z", "energy_kwh": "2", **change})
    assert (await client.receive_json())["success"] is False
    assert (await runtime.async_query("records", {}))["total"] == 0
    await hass.config_entries.async_unload(entry.entry_id)


async def test_new_preview_uses_current_accounting_timezone_and_edits_preserve_original(hass, tmp_path, hass_ws_client):
    entry, runtime = await setup_runtime(hass, tmp_path)
    hass.config.time_zone = "America/New_York"
    await runtime.async_refresh_config()
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "charge_tally/snapshot"})
    assert (await client.receive_json())["result"]["timezone"] == "America/New_York"
    await client.send_json({"id": 2, "type": "charge_tally/preview", "point_id": "point", "identity_id": "car",
        "start": "2025-01-01T00:00:00Z", "end": "2025-01-01T01:00:00Z", "energy_kwh": "1"})
    preview = (await client.receive_json())["result"]
    assert preview["record"]["timezone"] == "America/New_York"
    await client.send_json({"id": 3, "type": "charge_tally/commit", "token": preview["token"], "request_id": "tz"})
    record = (await client.receive_json())["result"]
    hass.config.time_zone = "Europe/London"
    await runtime.async_refresh_config()
    await client.send_json({"id": 4, "type": "charge_tally/preview", "record_id": record["id"], "expected_revision": 1, "note": "Original zone"})
    assert (await client.receive_json())["result"]["record"]["timezone"] == "America/New_York"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_subscription_ignores_foreign_change_and_reload_resolves_new_runtime(hass, tmp_path, hass_ws_client, hass_read_only_access_token, hass_read_only_user):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await second_point(hass, entry, runtime)
    anchor = next(p["identity_entity_id"] for p in (await runtime.async_snapshot())["points"] if p["id"] == "point")
    hass_read_only_user.permissions = PolicyPermissions({"entities": {"entity_ids": {anchor: True}}}, None)
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    await client.send_json({"id": 1, "type": "charge_tally/subscribe"})
    assert (await client.receive_json())["success"]
    assert (await client.receive_json())["event"]["generation"] == 1
    await runtime.async_command("start", {"point_id": "other", "request_id": "hidden"})
    await hass.async_block_till_done()
    await runtime.async_command("select_identity", {"point_id": "point", "identity_id": "car"})
    event = (await client.receive_json())["event"]
    assert event["generation"] == 2
    assert event["points"][0]["selected_identity_id"] == "car"
    assert event["summary"]["active_count"] == 0
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    terminal = await asyncio.wait_for(client.receive_json(), 2)
    assert terminal == {"id": 1, "type": "event", "event": {"type": "unloaded"}}
    await client.send_json({"id": 2, "type": "charge_tally/snapshot"})
    assert (await client.receive_json())["result"]["points"][0]["selected_identity_id"] == "car"
    await client.send_json({"id": 3, "type": "unsubscribe_events", "subscription": 1})
    assert (await client.receive_json())["success"]
    await client.send_json({"id": 4, "type": "charge_tally/subscribe"})
    assert (await client.receive_json())["success"]
    fresh = (await client.receive_json())["event"]
    assert fresh["generation"] == 1
    assert fresh["points"][0]["selected_identity_id"] == "car"
    await hass.config_entries.async_unload(entry.entry_id)
    assert (await client.receive_json())["event"] == {"type": "unloaded"}


async def test_anchor_rename_tracks_permissions_and_wrong_owner_fails_closed(hass, tmp_path, hass_ws_client, hass_read_only_access_token, hass_read_only_user):
    entry, runtime = await setup_runtime(hass, tmp_path)
    anchor = (await runtime.async_snapshot())["points"][0]["identity_entity_id"]
    registry = er.async_get(hass)
    registry.async_update_entity(anchor, new_entity_id="select.renamed_identity")
    hass_read_only_user.permissions = PolicyPermissions({"entities": {"entity_ids": {"select.renamed_identity": True}}}, None)
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    await client.send_json({"id": 1, "type": "charge_tally/snapshot", "point_id": "point"})
    assert (await client.receive_json())["result"]["points"][0]["identity_entity_id"] == "select.renamed_identity"
    registry.async_update_entity("select.renamed_identity", config_subentry_id="car")
    await client.send_json({"id": 2, "type": "charge_tally/snapshot", "point_id": "point"})
    assert (await client.receive_json())["error"]["code"] == "unauthorized"
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("command,payload", [("snapshot", {}), ("records", {}),
    ("query", {"start": "2020-01-01T00:00:00+00:00", "end": "2099-01-01T00:00:00+00:00"})])
async def test_queued_read_rechecks_scope_before_returning(hass, tmp_path, hass_read_only_user, monkeypatch, command, payload):
    import asyncio
    from custom_components.charge_tally.api import execute
    entry, runtime = await setup_runtime(hass, tmp_path)
    await runtime.async_command("start", {"point_id": "point", "request_id": "active"})
    anchor = (await runtime.async_snapshot())["points"][0]["identity_entity_id"]
    hass_read_only_user.permissions = PolicyPermissions({"entities": {"entity_ids": {anchor: True}}}, None)
    await runtime.async_pre_backup()
    entered = asyncio.Event()
    original_wait = runtime._gate.wait
    async def wait():
        entered.set()
        return await original_wait()
    monkeypatch.setattr(runtime._gate, "wait", wait)
    task = asyncio.create_task(execute(hass, hass_read_only_user, command, payload))
    await entered.wait()
    hass_read_only_user.permissions = PolicyPermissions({"entities": {"entity_ids": {}}}, None)
    runtime.async_post_backup()
    result = await task
    if command == "snapshot":
        assert result["points"] == []
    elif command == "records":
        assert result["total"] == 0
    else:
        assert result["active_count"] == 0
    await hass.config_entries.async_unload(entry.entry_id)


async def test_ws_snapshot_filters_permissions_and_hides_global_revision(hass, tmp_path, hass_ws_client, hass_read_only_access_token, hass_read_only_user):
    entry, runtime = await setup_runtime(hass, tmp_path)
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    hass_read_only_user.permissions = PolicyPermissions({"entities": {"entity_ids": {}}}, None)
    await client.send_json({"id": 1, "type": "charge_tally/snapshot"})
    result = await client.receive_json()
    assert result["success"] is True
    assert result["result"]["points"] == []
    assert result["result"]["summary"]["active_count"] == 0
    assert "revision" not in result["result"]
    await client.send_json({"id": 2, "type": "charge_tally/records", "point_id": "point"})
    assert (await client.receive_json())["error"]["code"] == "unauthorized"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_preview_bound_to_user_and_commit_reauthorizes(hass, tmp_path, hass_ws_client, hass_read_only_access_token, hass_read_only_user):
    entry, runtime = await setup_runtime(hass, tmp_path)
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    anchor = (await runtime.async_snapshot())["points"][0]["identity_entity_id"]
    hass_read_only_user.permissions = PolicyPermissions({"entities": {"entity_ids": {anchor: True}}}, None)
    await client.send_json({"id": 1, "type": "charge_tally/preview", "point_id": "point", "identity_id": "car",
        "start": "2025-01-01T00:00:00+00:00", "end": "2025-01-01T01:00:00+00:00", "energy_kwh": "2", "cost": "3"})
    response = await client.receive_json()
    assert response["success"] is True
    token = response["result"]["token"]
    assert (await runtime.async_query("records", {}, point_ids=["point"]))["total"] == 0
    er.async_get(hass).async_remove(anchor)
    await client.send_json({"id": 2, "type": "charge_tally/commit", "token": token, "request_id": "commit1"})
    assert (await client.receive_json())["error"]["code"] == "unauthorized"
    assert (await runtime.async_query("records", {}, point_ids=["point"]))["total"] == 0
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("payload", [
    {"type": "charge_tally/records", "limit": True},
    {"type": "charge_tally/records", "limit": 101},
    {"type": "charge_tally/query", "start": "2025-01-01", "end": "2025-01-02"},
    {"type": "charge_tally/void", "record_id": "foreign", "request_id": "x", "expected_revision": True},
])
async def test_ws_rejects_malformed_input(hass, tmp_path, hass_ws_client, hass_read_only_access_token, payload):
    entry, _ = await setup_runtime(hass, tmp_path)
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    await client.send_json({"id": 1, **payload})
    assert (await client.receive_json())["error"]["code"] == "invalid_format"
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("payload", [
    {}, {"calendar_period": "weekly"}, {"calendar_period": "daily", "start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"},
    {"start": "2026-01-01T00:00:00Z"},
])
async def test_calendar_query_strict_modes(hass, tmp_path, hass_ws_client, payload):
    entry, runtime = await setup_runtime(hass, tmp_path)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "charge_tally/query", **payload})
    assert (await client.receive_json())["success"] is False
    await hass.config_entries.async_unload(entry.entry_id)


async def test_calendar_query_matches_identity_snapshot(hass, tmp_path, hass_ws_client, monkeypatch):
    from datetime import datetime, UTC
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            fixed = datetime(2026, 1, 1, 12, tzinfo=UTC)
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
    monkeypatch.setattr("custom_components.charge_tally.runtime_store.datetime", Clock)
    entry, runtime = await setup_runtime(hass, tmp_path)
    preview = await runtime.async_command("preview", {"point_id": "point", "identity_id": "car", "start": "2026-01-01T00:00:00+08:00", "end": "2026-01-01T01:00:00+08:00", "energy_kwh": "10", "cost": "10"})
    await runtime.async_command("commit_preview", {"token": preview["token"], "request_id": "calendar"})
    hass.config.time_zone = "UTC"
    await runtime.async_refresh_config()
    client = await hass_ws_client(hass)
    for index, period in enumerate(("daily", "monthly", "yearly"), 1):
        await client.send_json({"id": index, "type": "charge_tally/query", "calendar_period": period, "identity_id": "car"})
        result = (await client.receive_json())["result"]
        snapshot = await runtime.async_snapshot()
        assert result == next(i for i in snapshot["identities"] if i["id"] == "car")["summaries"][period]
        assert result["energy_kwh"] == "10"
    await client.send_json({"id": 4, "type": "charge_tally/query", "start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"})
    assert (await client.receive_json())["result"]["energy_kwh"] == "0"
    await hass.config_entries.async_unload(entry.entry_id)
