"""Configured automatic detection switch."""
from homeassistant.components.switch import SwitchEntity

from .entity import TallyEntity, setup_entities


async def async_setup_entry(hass, entry, async_add_entities):
    setup_entities(hass, entry, async_add_entities, lambda runtime, sub: [DetectionSwitch(runtime, sub)] if sub.subentry_type == "point" and sub.data["input_mode"] != "energy" else [])


class DetectionSwitch(TallyEntity, SwitchEntity):
    def __init__(self, runtime, sub):
        super().__init__(runtime, sub.subentry_id, "detection", sub.data["name"] + " Detection")

    @property
    def is_on(self):
        return self.point["detection_enabled"] if self.point else False

    async def async_turn_on(self, **kwargs):
        await self.runtime.async_command("set_detection", {"point_id": self.id_, "enabled": True})

    async def async_turn_off(self, **kwargs):
        await self.runtime.async_command("set_detection", {"point_id": self.id_, "enabled": False})
