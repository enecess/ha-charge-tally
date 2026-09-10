"""Explicit repair flow for this integration's owned native helpers."""
import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow

from .native_helpers import HelperSetupError


class HelperRepairFlow(RepairsFlow):
    def __init__(self, entry_id, point_id):
        self.entry_id, self.point_id = entry_id, point_id

    async def async_step_init(self, user_input=None):
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        runtime = getattr(entry, "runtime_data", None) if entry else None
        if not runtime or self.point_id not in runtime.points:
            return self.async_abort(reason="point_removed")
        errors = {}
        if user_input is not None:
            try:
                result = await runtime.async_command("repair", {"point_id": self.point_id})
                if result["repaired"]:
                    return self.async_create_entry(data={})
            except (HelperSetupError, OSError, ValueError):
                pass
            errors["base"] = "repair_failed"
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}), errors=errors)


async def async_create_fix_flow(hass, issue_id, data):
    return HelperRepairFlow(data["entry_id"], data["point_id"])
