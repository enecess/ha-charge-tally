"""Exercise ledger options with real HA lifecycle and SQLite storage."""
import asyncio
import sqlite3
from datetime import timedelta
from decimal import Decimal

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.charge_tally.ledger import retained_currency


async def setup_entry(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(domain="charge_tally", title="Charge Tally", data={"currency": "CNY"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def open_currency(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    if result["type"] == FlowResultType.MENU:
        return await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "currency"})
    return result


async def add_subentry(hass, entry, kind, data):
    result = await hass.config_entries.subentries.async_init((entry.entry_id, kind), context={"source": "user"})
    return await hass.config_entries.subentries.async_configure(result["flow_id"], data)


async def add_point(hass, entry):
    hass.states.async_set("sensor.energy", "10", {"unit_of_measurement": "kWh", "state_class": "total_increasing", "device_class": "energy"})
    result = await add_subentry(hass, entry, "point", {"name": "Garage", "input_mode": "energy"})
    for data in (
        {"measurement": {"energy_entity": "sensor.energy", "resetting": True, "max_gap_seconds": 600}},
        {"mode": "static"}, {"value": "0.5"}, {"periods": []},
    ):
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], data)
    await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_options_change_unused_currency_and_reload_identity_units(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    await add_subentry(hass, entry, "identity", {"name": "Car", "enabled": True})
    await hass.async_block_till_done()
    identity_id = next(iter(entry.subentries))
    result = await open_currency(hass, entry)
    assert result["step_id"] == "currency"
    assert result["data_schema"]({}) == {"currency": "CNY"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"currency": " usd "})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.data == {"currency": "USD"}
    assert dict(entry.options) == {}
    assert identity_id in entry.subentries
    assert entry.runtime_data.snapshot["currency"] == "USD"
    assert await hass.async_add_executor_job(retained_currency, entry.runtime_data.path) == "USD"
    entity_id = er.async_get(hass).async_get_entity_id("sensor", "charge_tally", entry.entry_id + ":" + identity_id + ":total_cost")
    assert hass.states.get(entity_id).attributes["unit_of_measurement"] == "USD"


async def test_options_reject_invalid_currency_without_changes(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    result = await open_currency(hass, entry)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"currency": "invalid"})
    assert result["errors"] == {"base": "invalid_currency"}
    assert entry.data["currency"] == "CNY"
    assert await hass.async_add_executor_job(retained_currency, entry.runtime_data.path) == "CNY"


async def test_options_unchanged_currency_preserves_options_and_runtime(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    hass.config_entries.async_update_entry(entry, options={"future_option": True})
    await hass.async_block_till_done()
    runtime = entry.runtime_data
    result = await open_currency(hass, entry)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"currency": "CNY"})
    await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options == {"future_option": True}
    assert entry.runtime_data is runtime


async def test_locked_options_preserve_historical_amounts_and_revisions(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    await add_point(hass, entry)
    runtime = entry.runtime_data
    end = dt_util.utcnow()
    preview = await runtime.async_command("preview", {
        "point_id": next(iter(entry.subentries)), "identity_id": "unassigned",
        "start": (end - timedelta(hours=1)).isoformat(), "end": end.isoformat(),
        "energy_kwh": "10", "cost": "12.34",
    })
    record = await runtime.async_command("commit_preview", {"token": preview["token"], "request_id": "historical"})
    before = await runtime.async_query("record", {"record_id": record["id"]})
    result = await open_currency(hass, entry)
    assert result["step_id"] == "locked"
    await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert entry.data["currency"] == "CNY"
    assert await runtime.async_query("record", {"record_id": record["id"]}) == before
    assert Decimal(runtime.snapshot["summary"]["known_cost"]) == Decimal("12.34")


@pytest.mark.parametrize("remove_point", [False, True])
async def test_options_lock_used_ledger_even_after_point_removal(hass, tmp_path, remove_point):
    entry = await setup_entry(hass, tmp_path)
    await add_point(hass, entry)
    if remove_point:
        hass.config_entries.async_remove_subentry(entry, next(iter(entry.subentries)))
        await hass.async_block_till_done()
    before = await entry.runtime_data.async_snapshot()
    result = await open_currency(hass, entry)
    assert result["step_id"] == "locked"
    assert result["description_placeholders"]["currency"] == "CNY"
    assert "currency" not in result["data_schema"].schema
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.MENU
    assert entry.data["currency"] == "CNY"
    assert (await entry.runtime_data.async_snapshot())["records"] == before["records"]


async def test_options_recheck_when_point_added_while_form_open(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    result = await open_currency(hass, entry)
    await add_point(hass, entry)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"currency": "USD"})
    assert result["step_id"] == "locked"
    assert entry.data["currency"] == "CNY"
    assert await hass.async_add_executor_job(retained_currency, entry.runtime_data.path) == "CNY"


@pytest.mark.parametrize("mode", ["static", "tou"])
async def test_incomplete_point_cannot_relabel_prices_after_currency_change(hass, tmp_path, mode):
    entry = await setup_entry(hass, tmp_path)
    hass.states.async_set("sensor.energy", "10", {"unit_of_measurement": "kWh", "state_class": "total_increasing", "device_class": "energy"})
    point = await add_subentry(hass, entry, "point", {"name": "Garage", "input_mode": "energy"})
    for data in (
        {"measurement": {"energy_entity": "sensor.energy", "resetting": True, "max_gap_seconds": 600}},
        {"mode": mode},
    ):
        point = await hass.config_entries.subentries.async_configure(point["flow_id"], data)
    prices = [{"value": "0.5"}] if mode == "static" else [
        {"action": "add"}, {"start": "00:00", "end": "24:00", "price": "0.5"}, {"action": "finish"},
    ]
    for data in prices:
        point = await hass.config_entries.subentries.async_configure(point["flow_id"], data)
    assert point["step_id"] == "finish"
    result = await open_currency(hass, entry)
    await hass.config_entries.options.async_configure(result["flow_id"], {"currency": "USD"})
    await hass.async_block_till_done()
    point = await hass.config_entries.subentries.async_configure(point["flow_id"], {"periods": []})
    assert point["type"] == FlowResultType.ABORT
    assert point["reason"] == "config_changed"
    assert not entry.subentries


async def test_options_unloaded_entry_explains_unavailable_runtime(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    assert await hass.config_entries.async_unload(entry.entry_id)
    result = await open_currency(hass, entry)
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "runtime_unavailable"


async def test_options_report_write_failure_without_changing_currency(hass, tmp_path, monkeypatch):
    entry = await setup_entry(hass, tmp_path)
    result = await open_currency(hass, entry)

    def fail_write(*args):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(entry.runtime_data._store.ledger, "change_currency", fail_write)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"currency": "USD"})
    assert result["errors"] == {"base": "save_failed"}
    assert entry.data["currency"] == "CNY"
    assert entry.runtime_data._store.currency == "CNY"
    assert await hass.async_add_executor_job(retained_currency, entry.runtime_data.path) == "CNY"


async def test_options_reject_stale_form_after_another_currency_change(hass, tmp_path):
    entry = await setup_entry(hass, tmp_path)
    result = await open_currency(hass, entry)
    await entry.runtime_data.async_change_currency("USD", "CNY")
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"currency": "EUR"})
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "config_changed"
    assert entry.data["currency"] == "USD"


async def test_cancelled_currency_write_restores_ledger_binding(hass, tmp_path, monkeypatch):
    entry = await setup_entry(hass, tmp_path)
    runtime = entry.runtime_data
    writing, resume = asyncio.Event(), asyncio.Event()
    original = runtime._worker

    async def pause_write(function, *args):
        result = await original(function, *args)
        if function == runtime._store.change_currency and args[0] == "USD":
            writing.set()
            await resume.wait()
        return result

    monkeypatch.setattr(runtime, "_worker", pause_write)
    changing = hass.async_create_task(runtime.async_change_currency("USD", "CNY"))
    await writing.wait()
    changing.cancel()
    resume.set()
    with pytest.raises(asyncio.CancelledError):
        await changing
    assert entry.data["currency"] == "CNY"
    assert runtime._store.currency == "CNY"
    assert await hass.async_add_executor_job(retained_currency, runtime.path) == "CNY"


async def test_currency_change_rolls_back_if_point_added_during_write(hass, tmp_path, monkeypatch):
    entry = await setup_entry(hass, tmp_path)
    runtime = entry.runtime_data
    writing, resume = asyncio.Event(), asyncio.Event()
    original = runtime._worker

    async def pause_write(function, *args):
        result = await original(function, *args)
        if function == runtime._store.change_currency and args[0] == "USD":
            writing.set()
            await resume.wait()
        return result

    monkeypatch.setattr(runtime, "_worker", pause_write)
    changing = hass.async_create_task(runtime.async_change_currency("USD", "CNY"))
    await writing.wait()
    from homeassistant.config_entries import ConfigSubentry
    point = ConfigSubentry(subentry_id="race", subentry_type="point", title="Race", unique_id=None, data={
        "name": "Race", "input_mode": "energy", "energy_entity": "sensor.energy", "periods": [],
        "detection": {"enabled": False}, "price": {"mode": "static", "value": "0.5"},
    })
    hass.config_entries.async_add_subentry(entry, point)
    resume.set()
    with pytest.raises(ValueError, match="currency_locked"):
        await changing
    assert entry.data["currency"] == "CNY"
    assert runtime._store.currency == "CNY"
    assert await hass.async_add_executor_job(retained_currency, runtime.path) == "CNY"
    hass.config_entries.async_remove_subentry(entry, point.subentry_id)
