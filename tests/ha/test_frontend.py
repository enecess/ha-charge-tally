"""Frontend resources use the real HA storage collection."""
import re
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit
from homeassistant.components.lovelace import LovelaceData
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection, ResourceYAMLCollection
from homeassistant.setup import async_setup_component
from homeassistant.components.lovelace.dashboard import LovelaceStorage
import pytest


async def test_resource_registration_is_idempotent_and_serves_only_www(hass, tmp_path, hass_client):
    assert await async_setup_component(hass, "http", {})
    resources = ResourceStorageCollection(hass, LovelaceStorage(hass, None))
    hass.data[LOVELACE_DATA] = LovelaceData("storage", {}, resources, {})
    from custom_components.charge_tally import frontend
    await frontend.async_register(hass)
    await frontend.async_register(hass)
    items = resources.async_items()
    assert len(items) == 1
    assert items[0]["type"] == "module"
    assert items[0]["url"] == frontend.CARD_URL
    client = await hass_client()
    response = await client.get("/charge_tally/ledger.sqlite3")
    assert response.status == 404
    # Fetch the actual module graph, including versioned relative imports.
    queue, seen = [frontend.CARD_URL], set()
    while queue:
        url = queue.pop()
        if url in seen:
            continue
        seen.add(url)
        assert urlsplit(url).query == urlsplit(frontend.CARD_URL).query
        response = await client.get(url)
        assert response.status == 200
        assert "javascript" in response.headers["Content-Type"]
        assert "max-age" in response.headers["Cache-Control"]
        source = await response.text()
        queue.extend(urljoin(url, path) for path in re.findall(r"^import\s+(?:[^'\"]*?\s+from\s+)?['\"]([^'\"]+)['\"]", source, re.MULTILINE))
    assert urlsplit(frontend.CARD_URL).query == "v=0.1.2-4"
    paths = {urlsplit(url).path for url in seen}
    for module in ("card-controls", "card-view", "card-chart"):
        assert f"/charge_tally/{module}.js" in paths
    assert "/charge_tally/card-i18n.js" in paths
    for language in ("en", "zh-Hans", "de", "fr", "pl", "it"):
        assert f"/charge_tally/locales/{language}.js" in paths


async def test_yaml_resources_return_manual_module_configuration(hass, hass_client):
    assert await async_setup_component(hass, "http", {})
    resources = ResourceYAMLCollection([])
    hass.data[LOVELACE_DATA] = LovelaceData("yaml", {}, resources, {})
    from custom_components.charge_tally import frontend
    result = await frontend.async_register(hass)
    assert result == {"url": frontend.CARD_URL, "type": "module", "manual": True}
    assert resources.async_items() == []


async def test_existing_resource_loads_new_locales_after_upgrade(hass):
    assert await async_setup_component(hass, "http", {})
    resources = ResourceStorageCollection(hass, LovelaceStorage(hass, None))
    hass.data[LOVELACE_DATA] = LovelaceData("storage", {}, resources, {})
    await resources.async_get_info()
    old_url = "/charge_tally/charge-tally-card.js?v=0.1.2-3"
    original = await resources.async_create_item({"url": old_url, "res_type": "module"})
    from custom_components.charge_tally import frontend
    await frontend.async_register(hass)
    items = resources.async_items()
    assert len(items) == 1
    assert items[0]["id"] == original["id"]
    assert items[0]["url"] == frontend.CARD_URL
    assert items[0]["url"] != old_url


async def test_older_dashboard_mode_registers_the_card_without_duplicates(hass):
    assert await async_setup_component(hass, "http", {})
    resources = ResourceStorageCollection(hass, LovelaceStorage(hass, None))
    hass.data[LOVELACE_DATA] = SimpleNamespace(mode="storage", resources=resources)
    from custom_components.charge_tally import frontend
    assert (await frontend.async_register(hass))["manual"] is False
    await frontend.async_register(hass)
    assert [item["url"] for item in resources.async_items()] == [frontend.CARD_URL]


async def test_frontend_setup_failure_closes_runtime_and_removes_public_runtime(hass, tmp_path, monkeypatch):
    from custom_components.charge_tally import frontend
    from test_runtime import setup_runtime
    async def fail(hass):
        raise OSError("Static registration failed")
    monkeypatch.setattr(frontend, "async_setup", fail)
    with pytest.raises(AssertionError):
        await setup_runtime(hass, tmp_path)
    entry = hass.config_entries.async_entries("charge_tally")[0]
    assert entry.runtime_data._closed is True
    assert entry.entry_id not in hass.data.get("charge_tally", {})
