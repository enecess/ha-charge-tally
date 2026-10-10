"""Only administrators may manage NFC automation metadata."""

import pytest
from test_nfc_manager import setup_manager


async def request(client, id_, entry, command, **data):
    await client.send_json(
        {
            "id": id_,
            "type": f"charge_tally/nfc/{command}",
            "entry_id": entry.entry_id,
            **data,
        }
    )
    return await client.receive_json()


async def test_admin_can_prepare_readback_and_confirm(hass, tmp_path, hass_ws_client):
    entry, _, manager, draft = await setup_manager(hass, tmp_path)
    client = await hass_ws_client(hass)
    catalog = await request(client, 1, entry, "catalog")
    assert catalog["success"], catalog
    assert catalog["result"]["tags"][0]["id"] == "tag-a"
    prepared = await request(
        client,
        2,
        entry,
        "prepare",
        kind="create",
        rule_id=None,
        draft=draft,
        expected_revision=None,
        operation_id="create",
    )
    assert prepared["success"], prepared
    pending = prepared["result"]
    result = await request(
        client,
        3,
        entry,
        "confirm",
        operation_id="create",
        observed_config=pending["desired_config"],
    )
    assert result["success"], result
    assert (await manager.async_list())[0]["applied"]["version"] == 1
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "command,fields",
    [
        ("catalog", {}),
        ("list", {}),
        (
            "prepare",
            {
                "kind": "create",
                "rule_id": None,
                "draft": {},
                "expected_revision": None,
                "operation_id": "x",
            },
        ),
        ("inspect", {"rule_id": "x", "observed_config": None}),
        ("confirm", {"operation_id": "x", "observed_config": None}),
        ("cancel", {"operation_id": "x", "observed_config": None}),
    ],
)
async def test_management_denies_non_admin(
    hass, tmp_path, hass_ws_client, hass_read_only_access_token, command, fields
):
    entry, _, manager, _ = await setup_manager(hass, tmp_path)
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    result = await request(client, 1, entry, command, **fields)
    assert result["success"] is False
    assert result["error"]["code"] == "unauthorized"
    assert await manager.async_list() == []
    await hass.config_entries.async_unload(entry.entry_id)
