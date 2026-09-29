"""Native helpers are created and loaded by real Home Assistant integrations."""

from datetime import timedelta
from decimal import Decimal

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed_exact,
)


def owner(hass):
    entry = MockConfigEntry(
        domain="charge_tally", title="Charge Tally", data={"currency": "CNY"}
    )
    entry.add_to_hass(hass)
    return entry


def sources(hass, unit="W"):
    hass.states.async_set(
        "sensor.power",
        "1000" if unit == "W" else "1",
        {
            "unit_of_measurement": unit,
            "device_class": "power",
            "state_class": "measurement",
        },
    )
    hass.states.async_set(
        "sensor.normalized",
        "0",
        {
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "state_class": "total_increasing",
        },
    )


@pytest.mark.parametrize("unit", ["W", "kW"])
async def test_real_helpers_measure_reload_rename_and_remove(hass, freezer, unit):
    from custom_components.charge_tally.native_helpers import NativeHelpers

    sources(hass, unit)
    entry = owner(hass)
    point = {
        "name": "Garage",
        "input_mode": "power",
        "power_entity": "sensor.power",
        "periods": ["daily", "monthly", "yearly"],
    }
    helpers = NativeHelpers(hass, entry)
    result = await helpers.async_ensure("point1", point, "sensor.normalized")
    await hass.async_block_till_done()
    native = hass.config_entries.async_entries(
        "integration"
    ) + hass.config_entries.async_entries("utility_meter")
    assert len(native) == 4
    assert all(not helper.data for helper in native)
    integral = next(helper for helper in native if helper.domain == "integration")
    assert integral.options["method"] == "left"
    assert integral.options["unit_time"] == "h"
    assert integral.options["max_sub_interval"] == {"seconds": 60}
    assert integral.options.get("unit_prefix") == ("k" if unit == "W" else None)
    start = dt_util.utcnow()
    freezer.move_to(start + timedelta(seconds=60))
    async_fire_time_changed_exact(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    measured = hass.states.get(result["integral_entity_id"])
    assert measured.attributes["unit_of_measurement"] == "kWh"
    assert abs(Decimal(measured.state) - Decimal(".016667")) < Decimal(".000002")
    hass.states.async_set(
        "sensor.normalized",
        "2",
        {
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "state_class": "total_increasing",
        },
    )
    await hass.async_block_till_done()
    for entity_id in result["utility_entities"].values():
        assert Decimal(hass.states.get(entity_id).state) == 2
    registry = er.async_get(hass)
    registry.async_update_entity(
        result["integral_entity_id"], new_entity_id="sensor.renamed_integral"
    )
    await hass.async_block_till_done()
    for helper in native:
        assert await hass.config_entries.async_reload(helper.entry_id)
    hass.data.pop("charge_tally_native_helpers")
    again = await NativeHelpers(hass, entry).async_ensure(
        "point1", point, "sensor.normalized"
    )
    assert again["integral_entity_id"] == "sensor.renamed_integral"
    assert len(hass.config_entries.async_entries("integration")) == 1
    assert len(hass.config_entries.async_entries("utility_meter")) == 3
    await NativeHelpers(hass, entry).async_remove("point1")
    assert not hass.config_entries.async_entries("integration")
    assert not hass.config_entries.async_entries("utility_meter")
    assert hass.states.get("sensor.power") is not None
    assert hass.states.get("sensor.normalized") is not None


async def test_missing_owned_helper_requires_explicit_repair(hass):
    from custom_components.charge_tally.native_helpers import (
        HelperRepairRequired,
        NativeHelpers,
    )

    sources(hass)
    entry = owner(hass)
    point = {
        "name": "Garage",
        "input_mode": "power",
        "power_entity": "sensor.power",
        "periods": [],
    }
    await NativeHelpers(hass, entry).async_ensure("point1", point)
    helper = hass.config_entries.async_entries("integration")[0]
    await hass.config_entries.async_remove(helper.entry_id)
    with pytest.raises(HelperRepairRequired):
        await NativeHelpers(hass, entry).async_ensure("point1", point)
    assert not hass.config_entries.async_entries("integration")
    result = await NativeHelpers(hass, entry).async_repair("point1")
    assert result["integral_entity_id"]
    assert len(hass.config_entries.async_entries("integration")) == 1


async def test_energy_power_never_creates_integral_and_period_change_is_owned(hass):
    from custom_components.charge_tally.native_helpers import NativeHelpers

    sources(hass)
    entry = owner(hass)
    point = {
        "name": "Garage",
        "input_mode": "energy_power",
        "energy_entity": "sensor.external",
        "power_entity": "sensor.power",
        "periods": ["daily", "monthly"],
    }
    result = await NativeHelpers(hass, entry).async_ensure("point1", point)
    assert result == {"integral_entity_id": None, "utility_entities": {}}
    result = await NativeHelpers(hass, entry).async_ensure(
        "point1", point, "sensor.normalized"
    )
    assert not hass.config_entries.async_entries("integration")
    assert len(result["utility_entities"]) == 2
    point["periods"] = ["yearly"]
    result = await NativeHelpers(hass, entry).async_ensure(
        "point1", point, "sensor.normalized"
    )
    assert list(result["utility_entities"]) == ["yearly"]
    assert len(hass.config_entries.async_entries("utility_meter")) == 1


async def test_partial_creation_failure_retries_without_duplicate_integral(
    hass, monkeypatch
):
    from custom_components.charge_tally.native_helpers import (
        HelperRepairRequired,
        NativeHelpers,
    )

    sources(hass)
    entry = owner(hass)
    point = {
        "name": "Garage",
        "input_mode": "power",
        "power_entity": "sensor.power",
        "periods": ["daily"],
    }
    helpers = NativeHelpers(hass, entry)
    original = hass.config_entries.flow.async_init

    async def fail_meter(domain, **kwargs):
        if domain == "utility_meter":
            raise RuntimeError("injected native flow failure")
        return await original(domain, **kwargs)

    monkeypatch.setattr(hass.config_entries.flow, "async_init", fail_meter)
    with pytest.raises(HelperRepairRequired, match="uncertain_helper_creation"):
        await helpers.async_ensure("point1", point, "sensor.normalized")
    assert len(hass.config_entries.async_entries("integration")) == 1
    monkeypatch.setattr(hass.config_entries.flow, "async_init", original)
    hass.data.pop("charge_tally_native_helpers")
    result = await NativeHelpers(hass, entry).async_ensure(
        "point1", point, "sensor.normalized"
    )
    assert "daily" in result["utility_entities"]
    assert len(hass.config_entries.async_entries("integration")) == 1
    assert len(hass.config_entries.async_entries("utility_meter")) == 1


async def test_ownership_save_failure_preserves_durable_intent(hass, monkeypatch):
    from custom_components.charge_tally.native_helpers import NativeHelpers

    sources(hass)
    entry = owner(hass)
    point = {
        "name": "Garage",
        "input_mode": "power",
        "power_entity": "sensor.power",
        "periods": [],
    }
    helpers = NativeHelpers(hass, entry)
    original = helpers._store.async_save

    async def fail_id_save(data):
        roles = data["points"].get("point1", {}).get("roles", {})
        if roles.get("integral", {}).get("entry_id"):
            raise OSError("injected full disk")
        await original(data)

    monkeypatch.setattr(helpers._store, "async_save", fail_id_save)
    with pytest.raises(OSError, match="full disk"):
        await helpers.async_ensure("point1", point)
    assert len(hass.config_entries.async_entries("integration")) == 1
    hass.data.pop("charge_tally_native_helpers")
    result = await NativeHelpers(hass, entry).async_ensure("point1", point)
    assert result["integral_entity_id"]
    assert len(hass.config_entries.async_entries("integration")) == 1


async def test_recovery_refuses_token_match_with_changed_source(hass, monkeypatch):
    from custom_components.charge_tally.native_helpers import (
        HelperRepairRequired,
        NativeHelpers,
    )

    sources(hass)
    entry = owner(hass)
    point = {
        "name": "Garage",
        "input_mode": "power",
        "power_entity": "sensor.power",
        "periods": [],
    }
    helpers = NativeHelpers(hass, entry)
    original = helpers._store.async_save

    async def fail_id_save(data):
        roles = data["points"].get("point1", {}).get("roles", {})
        if roles.get("integral", {}).get("entry_id"):
            raise OSError("injected full disk")
        await original(data)

    monkeypatch.setattr(helpers._store, "async_save", fail_id_save)
    with pytest.raises(OSError):
        await helpers.async_ensure("point1", point)
    native = hass.config_entries.async_entries("integration")[0]
    hass.config_entries.async_update_entry(
        native, options={**native.options, "source": "sensor.other_power"}
    )
    await hass.async_block_till_done()
    hass.data.pop("charge_tally_native_helpers")
    with pytest.raises(HelperRepairRequired, match="changed_owned_helper"):
        await NativeHelpers(hass, entry).async_ensure("point1", point)
    assert len(hass.config_entries.async_entries("integration")) == 1


async def test_other_owners_helper_survives_removal(hass):
    from custom_components.charge_tally.native_helpers import NativeHelpers

    sources(hass)
    entry = owner(hass)
    external = await hass.config_entries.flow.async_init(
        "integration",
        context={"source": "user"},
        data={
            "name": "Garage integral",
            "source": "sensor.power",
            "method": "left",
            "unit_time": "h",
        },
    )
    point = {
        "name": "Garage",
        "input_mode": "power",
        "power_entity": "sensor.power",
        "periods": [],
    }
    await NativeHelpers(hass, entry).async_ensure("point1", point)
    assert len(hass.config_entries.async_entries("integration")) == 2
    await NativeHelpers(hass, entry).async_remove("point1")
    assert [
        helper.entry_id for helper in hass.config_entries.async_entries("integration")
    ] == [external["result"].entry_id]


async def test_concurrent_ensure_does_not_duplicate_native_helpers(hass):
    import asyncio

    from custom_components.charge_tally.native_helpers import NativeHelpers

    sources(hass)
    entry = owner(hass)
    point = {
        "name": "Garage",
        "input_mode": "power",
        "power_entity": "sensor.power",
        "periods": ["daily"],
    }
    first, second = await asyncio.gather(
        NativeHelpers(hass, entry).async_ensure("point1", point, "sensor.normalized"),
        NativeHelpers(hass, entry).async_ensure("point1", point, "sensor.normalized"),
    )
    assert first == second
    assert len(hass.config_entries.async_entries("integration")) == 1
    assert len(hass.config_entries.async_entries("utility_meter")) == 1


async def test_two_phase_ensure_preserves_normalized_source_for_repair(hass):
    from custom_components.charge_tally.native_helpers import NativeHelpers

    sources(hass)
    entry = owner(hass)
    point = {
        "name": "Garage",
        "input_mode": "power",
        "power_entity": "sensor.power",
        "periods": ["daily"],
    }
    await NativeHelpers(hass, entry).async_ensure("point1", point, "sensor.normalized")
    await NativeHelpers(hass, entry).async_ensure("point1", point)
    helper = hass.config_entries.async_entries("utility_meter")[0]
    await hass.config_entries.async_remove(helper.entry_id)
    result = await NativeHelpers(hass, entry).async_repair("point1")
    assert "daily" in result["utility_entities"]


async def test_disabled_owned_entry_requires_repair(hass):
    from homeassistant.config_entries import ConfigEntryDisabler

    from custom_components.charge_tally.native_helpers import (
        HelperRepairRequired,
        NativeHelpers,
    )

    sources(hass)
    entry = owner(hass)
    point = {
        "name": "Garage",
        "input_mode": "power",
        "power_entity": "sensor.power",
        "periods": [],
    }
    await NativeHelpers(hass, entry).async_ensure("point1", point)
    helper = hass.config_entries.async_entries("integration")[0]
    await hass.config_entries.async_set_disabled_by(
        helper.entry_id, ConfigEntryDisabler.USER
    )
    with pytest.raises(HelperRepairRequired):
        await NativeHelpers(hass, entry).async_ensure("point1", point)
    assert len(hass.config_entries.async_entries("integration")) == 1


async def test_kw_integral_added_prefix_requires_repair_and_restores_kwh(hass, freezer):
    from custom_components.charge_tally.native_helpers import (
        HelperRepairRequired,
        NativeHelpers,
    )

    sources(hass, "kW")
    entry = owner(hass)
    point = {
        "name": "Garage",
        "input_mode": "power",
        "power_entity": "sensor.power",
        "periods": [],
    }
    result = await NativeHelpers(hass, entry).async_ensure("point1", point)
    native = hass.config_entries.async_entries("integration")[0]
    hass.config_entries.async_update_entry(
        native, options={**native.options, "unit_prefix": "k"}
    )
    assert await hass.config_entries.async_reload(native.entry_id)
    await hass.async_block_till_done()
    assert (
        hass.states.get(result["integral_entity_id"]).attributes["unit_of_measurement"]
        != "kWh"
    )

    with pytest.raises(HelperRepairRequired, match="changed_owned_helper"):
        await NativeHelpers(hass, entry).async_ensure("point1", point)
    assert len(hass.config_entries.async_entries("integration")) == 1

    repaired = await NativeHelpers(hass, entry).async_repair("point1")
    current = hass.config_entries.async_entries("integration")
    assert len(current) == 1
    assert current[0].entry_id != native.entry_id
    assert current[0].options.get("unit_prefix") is None
    freezer.move_to(dt_util.utcnow() + timedelta(seconds=60))
    async_fire_time_changed_exact(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    measured = hass.states.get(repaired["integral_entity_id"])
    assert measured.attributes["unit_of_measurement"] == "kWh"
    assert abs(Decimal(measured.state) - Decimal(".016667")) < Decimal(".000002")


@pytest.mark.parametrize("failure_stage", ["token", "entry_id"])
@pytest.mark.parametrize("failure_kind", ["write", "serialization"])
@pytest.mark.parametrize("restart", [False, True])
async def test_store_silent_failure_blocks_creation_or_recovers_owned_helper(
    hass,
    monkeypatch,
    failure_stage,
    failure_kind,
    restart,
):
    """A swallowed Store failure must not lose ownership or duplicate helpers."""
    from homeassistant.helpers import storage
    from homeassistant.util.file import WriteError
    from homeassistant.util.json import SerializationError, json_loads, load_json

    from custom_components.charge_tally.native_helpers import (
        HelperSetupError,
        NativeHelpers,
    )

    sources(hass)
    entry = owner(hass)
    point = {
        "name": "Garage",
        "input_mode": "power",
        "power_entity": "sensor.power",
        "periods": [],
    }
    helpers = NativeHelpers(hass, entry)
    original_write = storage.write_utf8_file_atomic
    original_prepare = storage.json_helper.prepare_save_json

    def should_fail(data):
        if data.get("key") != helpers._store.key:
            return False
        owned = (
            data["data"]["points"]
            .get("point1", {})
            .get("roles", {})
            .get("integral", {})
        )
        return bool(owned) and bool(owned.get("entry_id")) == (
            failure_stage == "entry_id"
        )

    def fail_write(path, data, *args, **kwargs):
        if path == helpers._store.path and should_fail(json_loads(data)):
            raise WriteError("injected disk failure")
        return original_write(path, data, *args, **kwargs)

    def fail_serialization(data, *args, **kwargs):
        if should_fail(data):
            raise SerializationError("injected serialization failure")
        return original_prepare(data, *args, **kwargs)

    with monkeypatch.context() as failing_storage:
        if failure_kind == "write":
            failing_storage.setattr(storage, "write_utf8_file_atomic", fail_write)
        else:
            failing_storage.setattr(
                storage.json_helper, "prepare_save_json", fail_serialization
            )
        with pytest.raises(HelperSetupError, match="helper_storage_save_failed"):
            await helpers.async_ensure("point1", point)

    native = hass.config_entries.async_entries("integration")
    persisted = await hass.async_add_executor_job(load_json, helpers._store.path)
    roles = persisted["data"]["points"]["point1"]["roles"]
    if failure_stage == "token":
        assert native == []
        assert roles == {}
    else:
        assert len(native) == 1
        assert roles["integral"]["creation_token"] == native[0].unique_id
        assert "entry_id" not in roles["integral"]

    if restart:
        hass.data.pop("charge_tally_native_helpers")
        helpers = NativeHelpers(hass, entry)
    result = await helpers.async_ensure("point1", point)
    assert result["integral_entity_id"]
    current = hass.config_entries.async_entries("integration")
    assert len(current) == 1
    if native:
        assert current[0].entry_id == native[0].entry_id
