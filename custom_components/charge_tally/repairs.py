"""Explicit repair flow for this integration's owned native helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow

from .native_helpers import HelperSetupError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.data_entry_flow import FlowResult


class HelperRepairFlow(RepairsFlow):
    """Confirm recreation of a point's integration-owned helpers."""

    def __init__(self, entry_id: str, point_id: str) -> None:
        self.entry_id, self.point_id = entry_id, point_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Start the explicit helper repair confirmation."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Repair helpers after confirmation, reporting recoverable failures."""
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        runtime = getattr(entry, "runtime_data", None) if entry else None
        if not runtime or self.point_id not in runtime.points:
            return self.async_abort(reason="point_removed")
        errors = {}
        if user_input is not None:
            try:
                result = await runtime.async_command(
                    "repair", {"point_id": self.point_id}
                )
                if result["repaired"]:
                    return self.async_create_entry(data={})
            except (HelperSetupError, OSError, ValueError):
                pass
            errors["base"] = "repair_failed"
        return self.async_show_form(
            step_id="confirm", data_schema=vol.Schema({}), errors=errors
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> HelperRepairFlow:
    """Create a confirmation flow for an integration-owned repair issue."""
    issue_data = cast(dict[str, str], data)
    return HelperRepairFlow(issue_data["entry_id"], issue_data["point_id"])
