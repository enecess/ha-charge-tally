"""Charge Tally integration."""


async def async_setup_entry(hass, entry):
    """Load the ledger and actual HA entity platforms."""
    from .runtime import Runtime
    runtime = Runtime(hass, entry)
    entry.runtime_data = runtime
    try:
        await runtime.async_start()
        await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "select", "switch"])
        await runtime.async_finish_helpers()
    except BaseException:
        await runtime.async_close()
        raise
    entry.async_on_unload(entry.add_update_listener(_async_update))
    hass.data.setdefault("charge_tally", {})[entry.entry_id] = runtime
    return True


async def _async_update(hass, entry):
    await entry.runtime_data.async_refresh_config()


async def async_unload_entry(hass, entry):
    """Drain pending work before releasing the database worker."""
    if not await hass.config_entries.async_unload_platforms(entry, ["sensor", "select", "switch"]):
        return False
    await entry.runtime_data.async_close()
    hass.data.get("charge_tally", {}).pop(entry.entry_id, None)
    return True
