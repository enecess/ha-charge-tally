"""The NFC manager is reached from integration options, not a dashboard card."""

from homeassistant.components.frontend import DATA_PANELS
from homeassistant.data_entry_flow import FlowResultType
from test_runtime import setup_runtime


async def test_options_offer_hidden_admin_manager_link(hass, tmp_path):
    entry, _ = await setup_runtime(hass, tmp_path)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "nfc" in result["menu_options"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "nfc"}
    )
    assert result["type"] == FlowResultType.FORM
    assert (
        result["description_placeholders"]["url"]
        == f"/charge-tally-nfc?entry_id={entry.entry_id}"
    )
    panel = hass.data[DATA_PANELS]["charge-tally-nfc"]
    assert panel.require_admin
    assert panel.sidebar_title is None
    await hass.config_entries.async_unload(entry.entry_id)
