"""Charge Tally integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

    from .runtime import Runtime

    type ChargeTallyConfigEntry = ConfigEntry[Runtime]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register actions even when no ledger entry can be loaded."""
    from .api import async_register

    async_register(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ChargeTallyConfigEntry) -> bool:
    """Load the ledger and actual HA entity platforms."""
    from .runtime import Runtime

    runtime = Runtime(hass, entry)
    entry.runtime_data = runtime
    try:
        await runtime.async_start()
        await hass.config_entries.async_forward_entry_setups(
            entry, ["sensor", "select", "switch"]
        )
        await runtime.async_finish_helpers()
        from .frontend import async_setup

        await async_setup(hass)
        from .export_api import async_register_export

        async_register_export(hass)
    except BaseException:
        await runtime.async_close()
        raise
    entry.async_on_unload(entry.add_update_listener(_async_update))
    hass.data.setdefault("charge_tally", {})[entry.entry_id] = runtime
    return True


async def _async_update(hass: HomeAssistant, entry: ChargeTallyConfigEntry) -> None:
    if entry.runtime_data.configured_currency != entry.data["currency"]:
        await hass.config_entries.async_reload(entry.entry_id)
    else:
        await entry.runtime_data.async_refresh_config()


async def async_unload_entry(
    hass: HomeAssistant, entry: ChargeTallyConfigEntry
) -> bool:
    """Drain pending work before releasing the database worker."""
    if not await hass.config_entries.async_unload_platforms(
        entry, ["sensor", "select", "switch"]
    ):
        return False
    await entry.runtime_data.async_close()
    hass.data.get("charge_tally", {}).pop(entry.entry_id, None)
    return True


async def async_remove_entry(
    hass: HomeAssistant, entry: ChargeTallyConfigEntry
) -> None:
    """Permanently clear owned data when the entire integration is removed."""
    from .cleanup import async_remove_entry_data

    await async_remove_entry_data(hass, entry)
