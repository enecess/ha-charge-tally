"""Delete integration-owned data only at explicit removal or fresh creation."""

import asyncio
from pathlib import Path

from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .native_helpers import NativeHelpers


def reset_ledger_files(path):
    """Remove known SQLite files without touching other configuration files."""
    directory = Path(path)
    for name in ("ledger.sqlite3", "ledger.backup.sqlite3"):
        for suffix in ("", "-journal", "-wal", "-shm"):
            (directory / (name + suffix)).unlink(missing_ok=True)


def _lock(hass):
    return hass.data.setdefault(f"{DOMAIN}_lifecycle_lock", asyncio.Lock())


async def _async_reset_ledger(hass):
    """Drain filesystem work before allowing another lifecycle operation."""
    task = hass.async_add_executor_job(reset_ledger_files, hass.config.path(DOMAIN))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


async def async_prepare_new_ledger(hass):
    """A valid new configuration replaces data orphaned by older releases."""
    async with _lock(hass):
        if hass.config_entries.async_entries(DOMAIN):
            raise ValueError("single_instance_allowed")
        # A failed HA unload may leave a removed entry's worker alive.
        runtimes = hass.data.get(DOMAIN, {})
        for entry_id, runtime in list(runtimes.items()):
            await runtime.async_close()
            runtimes.pop(entry_id, None)
        if hass.config_entries.async_entries(DOMAIN):
            raise ValueError("single_instance_allowed")
        await _async_reset_ledger(hass)


async def async_remove_entry_data(hass, entry):
    """Close all writers before deleting this owner's private persistence."""
    async with _lock(hass):
        runtime = getattr(entry, "runtime_data", None)
        if runtime is not None:
            await runtime.async_close()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        try:
            await NativeHelpers(hass, entry).async_remove_all()
        finally:
            await Store(hass, 1, f"{DOMAIN}.nfc.{entry.entry_id}").async_remove()
            # A delayed callback must not erase a newly created entry's ledger.
            if not hass.config_entries.async_entries(DOMAIN):
                await _async_reset_ledger(hass)
