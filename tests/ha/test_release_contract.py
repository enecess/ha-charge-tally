"""Release metadata and native UI descriptions match the supported HA API."""
import json
from pathlib import Path

import pytest
import yaml
from homeassistant.helpers import entity_registry as er, selector

from test_runtime import setup_runtime


COMPONENT = Path(__file__).parents[2] / "custom_components" / "charge_tally"


def test_parent_is_discoverable():
    assert json.loads((COMPONENT / "manifest.json").read_text())["integration_type"] == "service"


def test_action_entity_selection_is_optional():
    services = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    for name in ("start", "end", "reassign"):
        assert "target" not in services[name]
        field = services[name]["fields"]["entity_id"]
        assert field["required"] is False
        validated = selector.validate_selector(field["selector"])
        assert validated["entity"]["multiple"] is False
        assert validated["entity"]["filter"] == [{"integration": "charge_tally", "domain": ["select"]}]
        for language in ("en", "zh-Hans"):
            strings = json.loads((COMPONENT / "translations" / f"{language}.json").read_text())
            assert strings["services"][name]["fields"]["entity_id"]["description"]


@pytest.mark.parametrize("value", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"])
async def test_extreme_utc_date_is_invalid_format(hass, tmp_path, hass_ws_client, value):
    entry, _ = await setup_runtime(hass, tmp_path)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "charge_tally/query", "start": value, "end": value})
    result = await client.receive_json()
    assert result["error"]["code"] == "invalid_format"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_native_record_and_identity_precision_is_display_only(hass, tmp_path):
    entry, runtime = await setup_runtime(hass, tmp_path)
    registry = er.async_get(hass)
    for id_, prefix in (("point", "record"), ("car", "total")):
        for metric, precision in (("energy", 3), ("cost", 2)):
            entity_id = registry.async_get_entity_id("sensor", "charge_tally", f"{entry.entry_id}:{id_}:{prefix}_{metric}")
            assert registry.async_get(entity_id).options.get("sensor", {}).get("suggested_display_precision") == precision
    preview = await runtime.async_command("preview", {"point_id": "point", "identity_id": "car",
        "start": "2025-01-01T00:00:00Z", "end": "2025-01-01T01:00:00Z",
        "energy_kwh": "1.123456789123456789", "cost": "0.123456789123456789"})
    assert preview["record"]["energy_kwh"] == "1.123456789123456789"
    assert preview["record"]["known_cost"] == "0.123456789123456789"
    await hass.config_entries.async_unload(entry.entry_id)
