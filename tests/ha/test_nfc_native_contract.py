"""Exercise the HA interfaces used by the managed NFC editor."""

from copy import deepcopy

import pytest
from homeassistant.components.config import automation as automation_config
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component


async def async_setup_nfc_native(hass, tmp_path):
    """Set up real UI-managed automations without loading the whole frontend."""
    (tmp_path / "automations.yaml").write_text("[]\n", encoding="utf-8")
    (tmp_path / "configuration.yaml").write_text(
        "automation: !include automations.yaml\n", encoding="utf-8"
    )
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "websocket_api", {})
    assert await async_setup_component(hass, "tag", {})
    assert await async_setup_component(hass, "automation", {"automation": []})
    automation_config.async_setup(hass)
    await hass.async_start()


def native_config():
    """Return an independently specified device/default automation."""
    return {
        "alias": "NFC contract",
        "triggers": [{"trigger": "tag", "tag_id": "tag-a"}],
        "mode": "queued",
        "actions": [
            {
                "choose": [
                    {
                        "conditions": [
                            {
                                "condition": "template",
                                "value_template": "{{ trigger.event.data.get('device_id') == 'phone-a' }}",
                            }
                        ],
                        "sequence": [
                            {"event": "nfc_selected", "event_data": {"identity": "car"}}
                        ],
                    }
                ],
                "default": [
                    {"event": "nfc_selected", "event_data": {"identity": "guest"}}
                ],
            }
        ],
    }


async def put_native(hass, client, config, id_="nfc-contract"):
    response = await client.post(f"/api/config/automation/config/{id_}", json=config)
    assert response.status == 200, await response.text()
    await hass.async_block_till_done()
    entity = er.async_get(hass).async_get_entity_id("automation", "automation", id_)
    assert entity is not None
    return entity


async def test_native_update_preserves_off_and_entity_rename(
    hass, tmp_path, hass_client
):
    await async_setup_nfc_native(hass, tmp_path)
    client = await hass_client()
    config = native_config()
    entity = await put_native(hass, client, config)
    assert hass.states.get(entity).state == "on"
    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": entity}, blocking=True
    )
    assert hass.states.get(entity).state == "off"
    registry = er.async_get(hass)
    registry.async_update_entity(entity, new_entity_id="automation.renamed_nfc")
    await hass.async_block_till_done()
    # HA renames a RestoreEntity before its previous ID's state is available.
    # Pause the renamed entity before exercising our editor's POST boundary.
    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": "automation.renamed_nfc"}, blocking=True
    )
    config["alias"] = "Changed visible name"
    entity = await put_native(hass, client, config)
    assert entity == "automation.renamed_nfc"
    assert hass.states.get(entity).state == "off"
    response = await client.get("/api/config/automation/config/nfc-contract")
    assert response.status == 200
    assert (await response.json())["alias"] == "Changed visible name"
    response = await client.delete("/api/config/automation/config/nfc-contract")
    assert response.status == 200
    await hass.async_block_till_done()
    assert hass.states.get(entity) is None
    assert (
        await client.get("/api/config/automation/config/nfc-contract")
    ).status == 404


@pytest.mark.parametrize("default", [True, False])
async def test_tag_choose_routes_once(
    hass, tmp_path, hass_client, hass_ws_client, default
):
    await async_setup_nfc_native(hass, tmp_path)
    client = await hass_client()
    config = native_config()
    if not default:
        config["actions"][0]["default"] = []
    await put_native(hass, client, config)
    results = []
    unsub = hass.bus.async_listen(
        "nfc_selected", lambda event: results.append(event.data)
    )
    try:
        for device in ("phone-a", "phone-b", None):
            event = {"tag_id": "tag-a"}
            if device:
                event["device_id"] = device
            hass.bus.async_fire("tag_scanned", event)
            await hass.async_block_till_done()
        assert results == (
            [{"identity": "car"}, {"identity": "guest"}, {"identity": "guest"}]
            if default
            else [{"identity": "car"}]
        )
        websocket = await hass_ws_client(hass)
        await websocket.send_json(
            {
                "id": 1,
                "type": "trace/list",
                "domain": "automation",
                "item_id": "nfc-contract",
            }
        )
        traces = await websocket.receive_json()
        assert traces["success"], traces
        assert len(traces["result"]) == 3
    finally:
        unsub()


async def test_native_config_requires_admin(
    hass, tmp_path, hass_client, hass_read_only_access_token
):
    await async_setup_nfc_native(hass, tmp_path)
    client = await hass_client(access_token=hass_read_only_access_token)
    for method in ("get", "post", "delete"):
        kwargs = {"json": deepcopy(native_config())} if method == "post" else {}
        response = await getattr(client, method)(
            "/api/config/automation/config/nfc-contract", **kwargs
        )
        assert response.status == 401


async def test_native_hidden_admin_panel(hass):
    from homeassistant.components.frontend import DATA_PANELS
    from homeassistant.components.panel_custom import async_register_panel

    await async_register_panel(
        hass,
        "charge-tally-nfc-contract",
        "charge-tally-nfc-panel",
        module_url="/charge_tally/nfc-panel.js",
        require_admin=True,
    )
    panel = hass.data[DATA_PANELS]["charge-tally-nfc-contract"]
    assert panel.require_admin is True
    assert panel.sidebar_title is None


async def test_compiled_rules_execute_stable_identity_once(hass, tmp_path, hass_client):
    from custom_components.charge_tally.nfc_rules import compile_automation

    await async_setup_nfc_native(hass, tmp_path)
    calls = []

    async def select(call):
        calls.append(dict(call.data))

    hass.services.async_register("charge_tally", "select_identity", select)
    config = compile_automation(
        "rule",
        "nfc-contract",
        {
            "point_id": "p",
            "tag_id": "tag-a",
            "device_bindings": [{"device_id": "phone-a", "identity_id": "car"}],
            "default_identity_id": "guest",
        },
        2,
        {"name": "NFC contract", "description": "Managed"},
    )
    client = await hass_client()
    await put_native(hass, client, config)
    for device in ("phone-a", "phone-b"):
        hass.bus.async_fire("tag_scanned", {"tag_id": "tag-a", "device_id": device})
    await hass.async_block_till_done()
    assert calls == [
        {"point_id": "p", "identity_id": "car", "rule_id": "rule", "rule_version": 2},
        {"point_id": "p", "identity_id": "guest", "rule_id": "rule", "rule_version": 2},
    ]
