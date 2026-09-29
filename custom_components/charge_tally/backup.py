"""Home Assistant backup hooks for quiescent consistent SQLite snapshots."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def async_pre_backup(hass: HomeAssistant) -> None:
    """Quiesce each loaded runtime before Home Assistant copies its storage."""
    for runtime in list(hass.data.get("charge_tally", {}).values()):
        await runtime.async_pre_backup()


async def async_post_backup(hass: HomeAssistant) -> None:
    """Resume loaded runtimes after the backup completes."""
    for runtime in list(hass.data.get("charge_tally", {}).values()):
        runtime.async_post_backup()
