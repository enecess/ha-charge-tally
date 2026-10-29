"""Entity registry anchors, native periods, and mutable identity summaries."""

from datetime import datetime, timedelta
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers import entity_registry as er
from test_runtime import ENERGY, setup_runtime, tick


async def test_entities_publish_live_record_and_identity_totals(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(hass, tmp_path, periods=["daily"])
    registry = er.async_get(hass)

    def entity(id_, key, domain="sensor"):
        return registry.async_get_entity_id(
            domain, "charge_tally", entry.entry_id + ":" + id_ + ":" + key
        )

    select_id = entity("point", "identity", "select")
    assert (await runtime.async_snapshot())["points"][0][
        "identity_entity_id"
    ] == select_id
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": "Car"},
        blocking=True,
    )
    record = await runtime.async_command(
        "start", {"point_id": "point", "request_id": "r1"}
    )
    await tick(hass, freezer, 30)
    hass.states.async_set("sensor.energy", "100.060", ENERGY)
    await hass.async_block_till_done()
    assert Decimal(hass.states.get(entity("point", "record_energy")).state) == Decimal(
        ".060"
    )
    total = hass.states.get(entity("car", "total_energy"))
    assert Decimal(total.state) == Decimal(".060")
    assert total.attributes.get("state_class") != "total_increasing"
    latest = (await runtime.async_snapshot())["records"][0]
    await runtime.async_command(
        "reassign",
        {
            "record_id": record["id"],
            "identity_id": "unassigned",
            "expected_revision": latest["revision"],
        },
    )
    await hass.async_block_till_done()
    assert Decimal(hass.states.get(entity("car", "total_energy")).state) == 0
    registry.async_update_entity(select_id, new_entity_id="select.renamed_identity")
    assert (await runtime.async_snapshot())["points"][0][
        "identity_entity_id"
    ] == "select.renamed_identity"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "override",
    [
        {"config_subentry_id": "car"},
        {"config_entry_id": "another_entry"},
        {"platform": "another_integration"},
        {"unique_id": "another_entity"},
        {"disabled": True},
    ],
)
async def test_rename_repair_does_not_adopt_unowned_or_disabled_entity(
    hass, tmp_path, override
):
    entry, _ = await setup_runtime(hass, tmp_path)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "select", "charge_tally", entry.entry_id + ":point:identity"
    )
    entity = hass.data["select"].get_entity(entity_id)
    candidate = SimpleNamespace(
        config_subentry_id=None,
        config_entry_id=entry.entry_id,
        platform="charge_tally",
        unique_id=entity.unique_id,
        disabled=False,
    )
    for key, value in override.items():
        setattr(candidate, key, value)
    with (
        patch.object(registry, "async_get", return_value=candidate),
        patch.object(registry, "async_update_entity") as update,
    ):
        await entity.async_added_to_hass()
        update.assert_not_called()
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "language,point_names,identity_names",
    [
        (
            "de",
            [
                "Garage Energie",
                "Garage Status",
                "Garage Energie des aktuellen/letzten Eintrags",
                "Garage Berechnete Kosten des aktuellen/letzten Eintrags",
                "Garage Identität",
                "Garage Ladeerkennung",
            ],
            [
                "Tagesenergie",
                "Berechnete Tageskosten",
                "Monatsenergie",
                "Berechnete Monatskosten",
                "Jahresenergie",
                "Berechnete Jahreskosten",
                "Gesamtenergie",
                "Berechnete Gesamtkosten",
            ],
        ),
        (
            "fr",
            [
                "Garage Énergie",
                "Garage État",
                "Garage Énergie de l’enregistrement actuel/dernier",
                "Garage Coût calculé de l’enregistrement actuel/dernier",
                "Garage Identité",
                "Garage Détection de la recharge",
            ],
            [
                "Énergie du jour",
                "Coût calculé du jour",
                "Énergie du mois",
                "Coût calculé du mois",
                "Énergie de l’année",
                "Coût calculé de l’année",
                "Énergie totale",
                "Coût total calculé",
            ],
        ),
        (
            "pl",
            [
                "Garage Energia",
                "Garage Stan",
                "Garage Energia bieżącego/ostatniego wpisu",
                "Garage Obliczony koszt bieżącego/ostatniego wpisu",
                "Garage Tożsamość",
                "Garage Wykrywanie ładowania",
            ],
            [
                "Energia dzienna",
                "Obliczony koszt dzienny",
                "Energia miesięczna",
                "Obliczony koszt miesięczny",
                "Energia roczna",
                "Obliczony koszt roczny",
                "Energia całkowita",
                "Obliczony koszt całkowity",
            ],
        ),
    ],
)
async def test_native_entity_names_translate_without_changing_ids_or_user_names(
    hass, tmp_path, language, point_names, identity_names
):
    hass.config.language = language
    entry, runtime = await setup_runtime(hass, tmp_path)
    registry = er.async_get(hass)
    expected = {
        ("sensor", "point", "energy"): ("Garage Energy", point_names[0], "Garage"),
        ("sensor", "point", "status"): ("Garage Status", point_names[1], "Garage"),
        ("sensor", "point", "record_energy"): (
            "Garage Record energy",
            point_names[2],
            "Garage",
        ),
        ("sensor", "point", "record_cost"): (
            "Garage Record cost",
            point_names[3],
            "Garage",
        ),
        ("select", "point", "identity"): ("Garage Identity", point_names[4], "Garage"),
        ("switch", "point", "detection"): (
            "Garage Detection",
            point_names[5],
            "Garage",
        ),
    }
    for identity_id, name in (("car", "Car"), ("unassigned", "Unassigned")):
        for index, key in enumerate(
            (
                "daily_energy",
                "daily_cost",
                "monthly_energy",
                "monthly_cost",
                "yearly_energy",
                "yearly_cost",
                "total_energy",
                "total_cost",
            )
        ):
            expected[("sensor", identity_id, key)] = (
                name + " " + key.replace("_", " "),
                name + " " + identity_names[index],
                name,
            )
    identifiers = {}
    for (domain, identity_id, key), (
        legacy_name,
        translated_name,
        owner_name,
    ) in expected.items():
        unique_id = entry.entry_id + ":" + identity_id + ":" + key
        entity_id = registry.async_get_entity_id(domain, "charge_tally", unique_id)
        assert entity_id == domain + "." + legacy_name.lower().replace(" ", "_")
        registered = registry.async_get(entity_id)
        assert registered.original_name == translated_name
        assert registered.translation_key == key
        assert hass.data[domain].get_entity(entity_id).translation_placeholders == {
            "name": owner_name
        }
        assert hass.states.get(entity_id).attributes["friendly_name"] == translated_name
        identifiers[unique_id] = entity_id
    assert hass.states.get("sensor.garage_status").state == "idle"
    assert hass.states.get("select.garage_identity").attributes["options"] == [
        "Car",
        "Unassigned",
    ]
    registry.async_update_entity(
        "sensor.garage_energy", new_entity_id="sensor.my_meter", name="My meter"
    )
    identifiers[entry.entry_id + ":point:energy"] = "sensor.my_meter"
    hass.config.language = "en"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    for unique_id, entity_id in identifiers.items():
        assert registry.async_get(entity_id).unique_id == unique_id
    assert registry.async_get("sensor.garage_status").original_name == "Garage Status"
    assert registry.async_get("sensor.my_meter").name == "My meter"
    assert hass.states.get("sensor.my_meter").attributes["friendly_name"] == "My meter"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_current_record_attributes_allow_automation_to_end_with_revision(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    registry = er.async_get(hass)
    status_id = registry.async_get_entity_id(
        "sensor", "charge_tally", entry.entry_id + ":point:status"
    )
    energy_id = registry.async_get_entity_id(
        "sensor", "charge_tally", entry.entry_id + ":point:record_energy"
    )
    assert hass.states.get(status_id).attributes.get("record_id") is None
    record = await runtime.async_command(
        "start", {"point_id": "point", "identity_id": "car", "request_id": "auto-start"}
    )
    await tick(hass, freezer, 30)
    hass.states.async_set("sensor.energy", "100.060", ENERGY)
    await hass.async_block_till_done()
    for entity_id in (status_id, energy_id):
        attributes = hass.states.get(entity_id).attributes
        assert attributes["record_id"] == record["id"]
        assert attributes["record_revision"] > record["revision"]
        assert attributes["identity_id"] == "car"
        assert attributes["start"] == record["start"]
        assert "records" not in attributes
    attrs = hass.states.get(status_id).attributes
    ended = await hass.services.async_call(
        "charge_tally",
        "end",
        {
            "record_id": attrs["record_id"],
            "expected_revision": attrs["record_revision"],
            "request_id": "auto-end",
        },
        blocking=True,
        return_response=True,
    )
    assert ended["status"] == "ended"
    await hass.async_block_till_done()
    assert hass.states.get(status_id).attributes.get("record_id") is None
    assert hass.states.get(energy_id).attributes["record_revision"] == ended["revision"]
    assert hass.states.get(energy_id).attributes["record_status"] == "ended"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_empty_point_scope_returns_no_global_counts(hass, tmp_path):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await runtime.async_command("start", {"point_id": "point", "request_id": "r1"})
    empty = await runtime.async_snapshot([])
    assert empty["points"] == []
    assert empty["records"] == []
    assert empty["summary"]["active_count"] == 0
    assert empty["summary"]["energy_kwh"] == "0"
    assert (await runtime.async_snapshot(["point"]))["summary"]["active_count"] == 1
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_parallel_points_and_scoped_queries_do_not_mix_identity_totals(
    hass, tmp_path, freezer
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    hass.states.async_set("sensor.energy_b", "50", ENERGY)
    data = {
        **entry.subentries["point"].data,
        "name": "Second",
        "input_mode": "energy",
        "energy_entity": "sensor.energy_b",
        "periods": ["daily"],
    }
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            subentry_id="second",
            subentry_type="point",
            title="Second",
            unique_id=None,
            data=MappingProxyType(data),
        ),
    )
    await hass.async_block_till_done()
    assert len(hass.config_entries.async_entries("utility_meter")) == 1
    await runtime.async_command(
        "start", {"point_id": "point", "identity_id": "car", "request_id": "a"}
    )
    await runtime.async_command(
        "start", {"point_id": "second", "identity_id": "unassigned", "request_id": "b"}
    )
    await tick(hass, freezer, 30)
    hass.states.async_set("sensor.energy", "101", ENERGY)
    hass.states.async_set("sensor.energy_b", "52", ENERGY)
    await hass.async_block_till_done()
    snapshot = await runtime.async_snapshot(["second"])
    assert len(snapshot["points"]) == 1
    assert Decimal(snapshot["summary"]["energy_kwh"]) == 2
    assert snapshot["summary"]["active_count"] == 1
    assert (
        next(i for i in snapshot["identities"] if i["id"] == "car")["summaries"][
            "total"
        ]["energy_kwh"]
        == "0"
    )
    result = await runtime.async_query("records", {}, point_ids=["second"])
    assert result["total"] == 1
    assert result["records"][0]["point_id"] == "second"
    assert (await runtime.async_query("summary", {}, point_ids=[]))["active_count"] == 0
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_detection_switch_tracks_reconfigured_point_capabilities(hass, tmp_path):
    entry, runtime = await setup_runtime(hass, tmp_path, mode="energy")
    registry = er.async_get(hass)
    unique_id = entry.entry_id + ":point:detection"
    assert registry.async_get_entity_id("switch", "charge_tally", unique_id) is None
    original = dict(entry.subentries["point"].data)
    for mode in ("energy_power", "energy", "power", "energy"):
        subentry = entry.subentries["point"]
        hass.config_entries.async_update_subentry(
            entry, subentry, data={**original, "input_mode": mode}
        )
        await hass.async_block_till_done()
        entity_id = registry.async_get_entity_id("switch", "charge_tally", unique_id)
        if mode == "energy":
            assert entity_id is None
        else:
            assert entity_id is not None
            assert hass.states.get(entity_id).state == "off"
            assert registry.async_get(entity_id).config_subentry_id == "point"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("known_first", [False, True])
async def test_incomplete_cost_entities_publish_known_subtotal(
    hass, tmp_path, freezer, known_first
):
    hass.states.async_set(
        "sensor.price",
        "2" if known_first else "unavailable",
        {"unit_of_measurement": "CNY/kWh"},
    )
    entry, runtime = await setup_runtime(
        hass,
        tmp_path,
        price={"mode": "dynamic", "entity_id": "sensor.price", "unit": "CNY/kWh"},
    )
    await runtime.async_command(
        "start", {"point_id": "point", "identity_id": "car", "request_id": "r1"}
    )
    await tick(hass, freezer, 30)
    hass.states.async_set("sensor.energy", "100.060", ENERGY)
    await hass.async_block_till_done()
    if known_first:
        hass.states.async_set(
            "sensor.price", "unavailable", {"unit_of_measurement": "CNY/kWh"}
        )
        await hass.async_block_till_done()
        await tick(hass, freezer, 30)
        hass.states.async_set("sensor.energy", "100.120", ENERGY)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    for id_, key in (
        ("point", "record_cost"),
        ("car", "daily_cost"),
        ("car", "monthly_cost"),
        ("car", "yearly_cost"),
        ("car", "total_cost"),
    ):
        entity_id = registry.async_get_entity_id(
            "sensor", "charge_tally", entry.entry_id + ":" + id_ + ":" + key
        )
        state = hass.states.get(entity_id)
        assert Decimal(state.state) == (Decimal(".120") if known_first else Decimal(0))
        assert state.attributes["has_known_cost"] is known_first
        assert state.attributes["cost_complete"] is False
        assert Decimal(state.attributes["known_cost"]) == (
            Decimal(".120") if known_first else Decimal(0)
        )
        assert "missing_price" in state.attributes["quality"]
    record = (await runtime.async_snapshot())["records"][0]
    assert Decimal(record["known_cost"]) == (
        Decimal(".120") if known_first else Decimal(0)
    )
    assert record["cost_complete"] is False
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_subentry_rename_updates_translated_names_without_reloading(
    hass, tmp_path
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    registry = er.async_get(hass)
    record = await runtime.async_command(
        "start", {"point_id": "point", "identity_id": "car", "request_id": "rename"}
    )
    registry.async_update_entity(
        "sensor.garage_energy", new_entity_id="sensor.my_meter", name="My meter"
    )
    await hass.async_block_till_done()
    for subentry_id, name in (("point", "Driveway"), ("car", "Truck")):
        subentry = entry.subentries[subentry_id]
        hass.config_entries.async_update_subentry(
            entry, subentry, title=name, data={**subentry.data, "name": name}
        )
        await hass.async_block_till_done()
    assert entry.runtime_data is runtime
    assert (await runtime.async_snapshot())["points"][0]["active_record"][
        "id"
    ] == record["id"]
    for entity_id, expected_name in (
        ("sensor.garage_status", "Driveway Status"),
        ("select.garage_identity", "Driveway Identity"),
        ("switch.garage_detection", "Driveway Detection"),
        ("sensor.car_daily_energy", "Truck daily energy"),
    ):
        assert hass.states.get(entity_id).attributes["friendly_name"] == expected_name
        assert registry.async_get(entity_id).original_name == expected_name
    assert registry.async_get("sensor.my_meter").original_name == "Driveway Energy"
    assert hass.states.get("sensor.my_meter").attributes["friendly_name"] == "My meter"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "period,start,end",
    [
        ("daily", "2026-09-28T00:00:00+08:00", "2026-09-29T00:00:00+08:00"),
        ("monthly", "2026-09-01T00:00:00+08:00", "2026-10-01T00:00:00+08:00"),
        ("yearly", "2026-01-01T00:00:00+08:00", "2027-01-01T00:00:00+08:00"),
    ],
)
async def test_identity_period_reset_is_bound_to_published_snapshot(
    hass, tmp_path, freezer, period, start, end
):
    boundary = datetime.fromisoformat(end)
    freezer.move_to(boundary - timedelta(minutes=2))
    entry, runtime = await setup_runtime(
        hass, tmp_path, price={"mode": "static", "value": "-2"}
    )
    record = await runtime.async_command(
        "start", {"point_id": "point", "identity_id": "car", "request_id": "period"}
    )
    await tick(hass, freezer, 30)
    hass.states.async_set("sensor.energy", "110", ENERGY)
    await hass.async_block_till_done()
    entity_id = "sensor.car_" + period + "_energy"
    sensor = hass.data["sensor"].get_entity(entity_id)
    assert Decimal(hass.states.get(entity_id).state) == 10
    assert sensor.last_reset == datetime.fromisoformat(start)
    assert datetime.fromisoformat(
        hass.states.get(entity_id).attributes["last_reset"]
    ) == datetime.fromisoformat(start)
    assert Decimal(hass.states.get("sensor.car_" + period + "_cost").state) == -20
    assert "last_reset" not in hass.states.get("sensor.car_total_energy").attributes
    # A correction is a signed delta within the same meter cycle.
    latest = (await runtime.async_snapshot())["records"][0]
    await runtime.async_command(
        "reassign",
        {
            "record_id": record["id"],
            "identity_id": "unassigned",
            "expected_revision": latest["revision"],
        },
    )
    await hass.async_block_till_done()
    assert Decimal(hass.states.get(entity_id).state) == 0
    assert sensor.last_reset == datetime.fromisoformat(start)
    unassigned = hass.data["sensor"].get_entity(
        "sensor.unassigned_" + period + "_energy"
    )
    assert Decimal(unassigned.native_value) == 10
    # Crossing wall-clock midnight alone must not reset an old snapshot.
    freezer.move_to(boundary)
    assert unassigned.last_reset == datetime.fromisoformat(start)
    assert Decimal(unassigned.native_value) == 10
    await tick(hass, freezer, 30)
    assert unassigned.last_reset == boundary
    assert Decimal(unassigned.native_value) == 0
    assert Decimal(hass.states.get("sensor.unassigned_total_energy").state) == 10
    assert await hass.config_entries.async_unload(entry.entry_id)
