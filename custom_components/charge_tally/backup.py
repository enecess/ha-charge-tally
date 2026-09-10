"""Home Assistant backup hooks for quiescent consistent SQLite snapshots."""


async def async_pre_backup(hass):
    for runtime in list(hass.data.get("charge_tally", {}).values()):
        await runtime.async_pre_backup()


async def async_post_backup(hass):
    for runtime in list(hass.data.get("charge_tally", {}).values()):
        runtime.async_post_backup()
