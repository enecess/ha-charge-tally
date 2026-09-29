"""Configured automatic detection switch."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity

from .entity import TallyEntity, setup_entities

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigSubentry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import ChargeTallyConfigEntry
    from .runtime import Runtime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ChargeTallyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Discover entities for the entry's configured point subentries."""
    await setup_entities(
        hass,
        entry,
        async_add_entities,
        lambda runtime, sub: (
            [DetectionSwitch(runtime, sub)]
            if sub.subentry_type == "point" and sub.data["input_mode"] != "energy"
            else []
        ),
    )


class DetectionSwitch(TallyEntity, SwitchEntity):
    """Control automatic session detection for a power-based point."""

    def __init__(self, runtime: Runtime, sub: ConfigSubentry) -> None:
        super().__init__(
            runtime,
            sub.subentry_id,
            "detection",
            sub.data["name"] + " Detection",
            sub.data["name"],
        )

    @property
    def is_on(self) -> bool:
        """Return whether automatic detection is enabled."""
        return self.point["detection_enabled"] if self.point else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable automatic session detection."""
        await self.runtime.async_command(
            "set_detection", {"point_id": self.id_, "enabled": True}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable automatic session detection."""
        await self.runtime.async_command(
            "set_detection", {"point_id": self.id_, "enabled": False}
        )
