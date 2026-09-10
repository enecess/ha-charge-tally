"""Exercise Charge Tally forms through the real HA flow manager."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "charge_tally"


@pytest.fixture(autouse=True)
def lifecycle_boundary():
    """Task 4 owns lifecycle; native helper tests never use this patch."""
    with patch("custom_components.charge_tally.async_setup_entry", create=True, new=AsyncMock(return_value=True)):
        yield


@pytest.fixture
def entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={"currency": "CNY"}, title="Charge Tally")
    entry.add_to_hass(hass)
    return entry


def sources(hass):
    hass.states.async_set("sensor.energy", "10", {"unit_of_measurement": "kWh", "state_class": "total_increasing", "device_class": "energy"})
    hass.states.async_set("sensor.power", "1000", {"unit_of_measurement": "W", "device_class": "power"})
    hass.states.async_set("sensor.price", ".7", {"unit_of_measurement": "CNY/kWh"})


async def advance(hass, result, data):
    return await hass.config_entries.subentries.async_configure(result["flow_id"], data)


async def point_until_price(hass, entry, mode="energy", detection=False):
    sources(hass)
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "point"), context={"source": "user"})
    assert result["step_id"] == "user"
    result = await advance(hass, result, {"name": "Garage", "input_mode": mode})
    assert result["step_id"] == "input"
    fields = result["data_schema"].schema["measurement"].schema.schema
    assert ("energy_entity" in fields) == (mode != "power")
    assert ("power_entity" in fields) == (mode != "energy")
    data = {"resetting": True, "max_gap_seconds": 600}
    if mode != "power":
        data["energy_entity"] = "sensor.energy"
    if mode != "energy":
        data.update(power_entity="sensor.power", detection_enabled=detection)
    result = await advance(hass, result, {"measurement": data})
    if detection:
        assert result["step_id"] == "detection"
        result = await advance(hass, result, {"start_w": 100, "end_w": 10, "start_seconds": 30, "end_seconds": 300})
    assert result["step_id"] == "price"
    return result


async def finish_static(hass, result, value=".5"):
    result = await advance(hass, result, {"mode": "static"})
    assert result["step_id"] == "static"
    result = await advance(hass, result, {"value": value})
    assert result["step_id"] == "finish"
    return await advance(hass, result, {"periods": ["daily", "monthly", "yearly"]})


@pytest.mark.parametrize("language, expected", [
    ("en", "Garage · Energy only · Static"), ("zh-Hans", "Garage · 仅电量 · 固定"),
    ("de", "Garage · Nur Energie · Fest"), ("fr", "Garage · Énergie uniquement · Fixe"),
    ("pl", "Garage · Tylko energia · Stała"),
])
async def test_final_summary_uses_localized_mode_labels(hass, entry, language, expected):
    hass.config.language = language
    result = await advance(hass, await point_until_price(hass, entry), {"mode": "static"})
    result = await advance(hass, result, {"value": "0.5"})
    assert result["description_placeholders"]["summary"] == expected


async def test_single_entry_currency_and_point_onboarding(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"currency": "NOT_A_CURRENCY"})
    assert result["errors"] == {"base": "invalid_currency"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"currency": "CNY"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {"currency": "CNY"}
    assert result["next_flow"][0] == "config_subentries_flow"
    next_flow = hass.config_entries.subentries.async_get(result["next_flow"][1])
    assert next_flow is not None
    duplicate = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert duplicate["reason"] == "single_instance_allowed"


@pytest.mark.parametrize(("mode", "detection"), [("energy", False), ("power", False), ("power", True), ("energy_power", True)])
async def test_input_paths_and_static_negative_price(hass, entry, mode, detection):
    result = await finish_static(hass, await point_until_price(hass, entry, mode, detection), "-.25")
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["price"] == {"mode": "static", "value": "-0.25"}
    assert result["data"]["detection"]["enabled"] == detection
    assert len(entry.subentries) == 1


async def test_duplicate_source_rejected_at_final_save(hass, entry):
    first = await point_until_price(hass, entry)
    second = await point_until_price(hass, entry)
    assert (await finish_static(hass, first))["type"] == FlowResultType.CREATE_ENTRY
    result = await finish_static(hass, second)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "duplicate_source"}
    assert len(entry.subentries) == 1


@pytest.mark.parametrize("unit", ["USD/kWh", "CNY/MW"])
async def test_dynamic_price_rejects_unit_currency_mismatch(hass, entry, unit):
    result = await point_until_price(hass, entry)
    hass.states.async_set("sensor.price", "1", {"unit_of_measurement": unit})
    result = await advance(hass, result, {"mode": "dynamic"})
    result = await advance(hass, result, {"entity_id": "sensor.price", "unit": "CNY/kWh"})
    assert result["errors"] == {"base": "invalid_price_unit"}


async def test_dynamic_missing_unit_requires_explicit_confirmation(hass, entry):
    result = await point_until_price(hass, entry)
    hass.states.async_set("sensor.price", "-.1")
    result = await advance(hass, result, {"mode": "dynamic"})
    result = await advance(hass, result, {"entity_id": "sensor.price"})
    assert result["errors"] == {"base": "invalid_price_unit"}
    result = await advance(hass, result, {"entity_id": "sensor.price", "unit": "CNY/kWh"})
    result = await advance(hass, result, {"periods": []})
    assert result["data"]["price"]["unit"] == "CNY/kWh"


async def test_tou_add_edit_remove_full_day_and_midnight(hass, entry):
    result = await point_until_price(hass, entry)
    result = await advance(hass, result, {"mode": "tou"})
    result = await advance(hass, result, {"action": "add"})
    result = await advance(hass, result, {"start": "00:00", "end": "08:00", "price": "-.1"})
    result = await advance(hass, result, {"action": "finish"})
    assert result["errors"] == {"base": "invalid_schedule"}
    result = await advance(hass, result, {"action": "add"})
    result = await advance(hass, result, {"start": "08:00", "end": "24:00", "price": ".8"})
    result = await advance(hass, result, {"action": "edit", "row": "1"})
    result = await advance(hass, result, {"start": "08:00", "end": "24:00", "price": ".6"})
    result = await advance(hass, result, {"action": "remove", "row": "0"})
    result = await advance(hass, result, {"action": "add"})
    result = await advance(hass, result, {"start": "00:00", "end": "08:00", "price": "0"})
    result = await advance(hass, result, {"action": "finish"})
    result = await advance(hass, result, {"periods": ["daily"]})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["price"]["schedule"] == [{"start": "08:00", "end": "24:00", "price": "0.6"}, {"start": "00:00", "end": "08:00", "price": "0"}]


async def test_identity_reconfigure_retains_stable_id_and_disabled_name_reuse(hass, entry):
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "identity"), context={"source": "user"})
    result = await advance(hass, result, {"name": "Alice", "enabled": True})
    old_id = next(iter(entry.subentries))
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "identity"), context={"source": "reconfigure", "subentry_id": old_id})
    result = await advance(hass, result, {"name": "Alice renamed", "enabled": False})
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[old_id].data == {"name": "Alice renamed", "enabled": False}
    hass.config_entries.async_remove_subentry(entry, old_id)
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "identity"), context={"source": "user"})
    await advance(hass, result, {"name": "Alice renamed", "enabled": True})
    assert next(iter(entry.subentries)) != old_id


async def test_running_reconfigure_refuses_source_changes_but_allows_price(hass, entry):
    await finish_static(hass, await point_until_price(hass, entry))
    subentry_id = next(iter(entry.subentries))
    old = deepcopy(dict(entry.subentries[subentry_id].data))

    async def busy(point_id, old_data, new_data):
        return False

    entry.runtime_data = SimpleNamespace(async_config_guard=busy)
    hass.states.async_set("sensor.energy2", "1", {"unit_of_measurement": "kWh", "state_class": "total_increasing"})
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "point"), context={"source": "reconfigure", "subentry_id": subentry_id})
    result = await advance(hass, result, {"name": "Garage", "input_mode": "energy"})
    result = await advance(hass, result, {"measurement": {"energy_entity": "sensor.energy2", "resetting": True, "max_gap_seconds": 600}})
    result = await finish_static(hass, result, ".7")
    assert result["reason"] == "point_busy"
    assert dict(entry.subentries[subentry_id].data) == old
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "point"), context={"source": "reconfigure", "subentry_id": subentry_id})
    result = await advance(hass, result, {"name": "Garage", "input_mode": "energy"})
    result = await advance(hass, result, {"measurement": {"energy_entity": "sensor.energy", "resetting": True, "max_gap_seconds": 600}})
    result = await finish_static(hass, result, ".7")
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[subentry_id].data["price"]["value"] == "0.7"


@pytest.mark.parametrize("change, error", [
    ({"detection": {"enabled": True, "start_w": 10, "end_w": 10, "start_seconds": 30, "end_seconds": 300}}, "invalid_detection"),
    ({"detection": {"enabled": True, "start_w": 10, "end_w": 0, "start_seconds": 0, "end_seconds": 300}}, "invalid_detection"),
    ({"price": {"mode": "tou", "schedule": [{"start": "00:00", "end": "00:00", "price": "1"}]}}, "invalid_schedule"),
    ({"max_gap_seconds": 0}, "invalid_gap"),
    ({"max_gap_seconds": "1e999"}, "invalid_gap"),
    ({"detection": {"enabled": True, "start_w": 10, "end_w": 0, "start_seconds": "1e999", "end_seconds": 300}}, "invalid_detection"),
])
def test_point_validation_rejects_invalid_configuration(change, error):
    from custom_components.charge_tally.config_validation import validate_point
    data = {"name": "Garage", "input_mode": "power", "power_entity": "sensor.power", "detection": {"enabled": False}, "price": {"mode": "static", "value": "0"}, "periods": []}
    data.update(change)
    with pytest.raises(ValueError, match=error):
        validate_point(data, [])


async def test_detection_form_threshold_and_duration_errors(hass, entry):
    sources(hass)
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "point"), context={"source": "user"})
    result = await advance(hass, result, {"name": "Garage", "input_mode": "power"})
    result = await advance(hass, result, {"measurement": {"power_entity": "sensor.power", "detection_enabled": True, "resetting": True, "max_gap_seconds": 600}})
    for changes in ({"end_w": 100}, {"start_seconds": 0}, {"end_seconds": 0}):
        result = await advance(hass, result, {"start_w": 100, "end_w": 10, "start_seconds": 30, "end_seconds": 300, **changes})
        assert result["step_id"] == "detection"
        assert result["errors"] == {"base": "invalid_detection"}


@pytest.mark.parametrize("attributes,error", [
    ({"unit_of_measurement": "kWh", "state_class": "measurement"}, "invalid_energy_source"),
    ({"unit_of_measurement": "W", "state_class": "total"}, "invalid_energy_source"),
])
async def test_energy_form_rejects_non_cumulative_source(hass, entry, attributes, error):
    hass.states.async_set("sensor.energy", "1", attributes)
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "point"), context={"source": "user"})
    result = await advance(hass, result, {"name": "Garage", "input_mode": "energy"})
    result = await advance(hass, result, {"measurement": {"energy_entity": "sensor.energy", "resetting": True, "max_gap_seconds": 600}})
    assert result["errors"] == {"base": error}


async def test_tou_overlapping_rows_and_cross_midnight(hass, entry):
    result = await advance(hass, await point_until_price(hass, entry), {"mode": "tou"})
    for row in ({"start": "22:00", "end": "06:00", "price": "0"}, {"start": "05:00", "end": "22:00", "price": "1"}):
        result = await advance(hass, result, {"action": "add"})
        result = await advance(hass, result, row)
    result = await advance(hass, result, {"action": "finish"})
    assert result["errors"] == {"base": "invalid_schedule"}
    result = await advance(hass, result, {"action": "edit", "row": "1"})
    result = await advance(hass, result, {"start": "06:00", "end": "22:00", "price": "1"})
    result = await advance(hass, result, {"action": "finish"})
    assert (await advance(hass, result, {"periods": []}))["type"] == FlowResultType.CREATE_ENTRY


async def test_multilingual_grouped_form_resources_load_in_ha(hass):
    from homeassistant.helpers.translation import async_get_translations
    for language, expected in (
        ("en", "Cumulative energy sensor"), ("zh-Hans", "累计电量实体"),
        ("de", "Sensor für kumulierte Energie"), ("fr", "Capteur d’énergie cumulée"),
        ("pl", "Czujnik skumulowanej energii"),
    ):
        strings = await async_get_translations(hass, language, "config_subentries", {DOMAIN})
        assert strings[f"component.{DOMAIN}.config_subentries.point.step.input.sections.measurement.data.energy_entity"] == expected


async def test_reconfigure_does_not_overwrite_change_while_guard_awaits(hass, entry):
    await finish_static(hass, await point_until_price(hass, entry))
    subentry_id = next(iter(entry.subentries))

    async def concurrent_edit(point_id, old_data, new_data):
        subentry = entry.subentries[point_id]
        hass.config_entries.async_update_subentry(entry, subentry, data={**subentry.data, "name": "Concurrent rename"})
        return True

    entry.runtime_data = SimpleNamespace(async_config_guard=concurrent_edit)
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "point"), context={"source": "reconfigure", "subentry_id": subentry_id})
    result = await advance(hass, result, {"name": "Garage", "input_mode": "energy"})
    result = await advance(hass, result, {"measurement": {"energy_entity": "sensor.energy", "resetting": False, "max_gap_seconds": 600}})
    result = await finish_static(hass, result)
    assert result["reason"] == "config_changed"
    assert entry.subentries[subentry_id].data["name"] == "Concurrent rename"


@pytest.mark.parametrize("name", ["Unassigned", " unASSIGNED "])
async def test_reserved_identity_rejected_before_create_and_reconfigure(hass, entry, name):
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "identity"), context={"source": "user"})
    result = await advance(hass, result, {"name": name, "enabled": True})
    assert result["errors"] == {"base": "duplicate_name"}
    assert not entry.subentries
    result = await advance(hass, result, {"name": "Car", "enabled": False})
    old_id = next(iter(entry.subentries))
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "identity"), context={"source": "reconfigure", "subentry_id": old_id})
    result = await advance(hass, result, {"name": name, "enabled": True})
    assert result["errors"] == {"base": "duplicate_name"}
    assert entry.subentries[old_id].data == {"name": "Car", "enabled": False}


async def test_currency_flow_uses_retained_ledger_binding(hass):
    from pathlib import Path
    from custom_components.charge_tally.runtime_store import RuntimeStore
    def create():
        store = RuntimeStore(str(Path(hass.config.path("charge_tally/ledger.sqlite3"))), "CNY", "UTC")
        store.ledger.close()
    await hass.async_add_executor_job(create)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"currency": "USD"})
    assert result["errors"] == {"base": "currency_mismatch"}
    assert not hass.config_entries.async_entries(DOMAIN)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"currency": "CNY"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["currency"] == "CNY"
