"""Per-point next-record identity selection."""
from homeassistant.components.select import SelectEntity

from .entity import TallyEntity, setup_entities


async def async_setup_entry(hass, entry, async_add_entities):
    await setup_entities(hass, entry, async_add_entities, lambda runtime, sub: [IdentitySelect(runtime, sub)] if sub.subentry_type == "point" else [])


class IdentitySelect(TallyEntity, SelectEntity):
    def __init__(self, runtime, sub):
        super().__init__(runtime, sub.subentry_id, "identity", sub.data["name"] + " Identity", sub.data["name"])

    @property
    def options(self):
        return [i["name"] for i in self.runtime.snapshot["identities"] if i.get("active", True)]

    @property
    def current_option(self):
        return next((i["name"] for i in self.runtime.snapshot["identities"] if self.point and i["id"] == self.point["selected_identity_id"]), None)

    async def async_select_option(self, option):
        identity = next((i for i in self.runtime.snapshot["identities"] if i["name"] == option and i.get("active", True)), None)
        if identity is None:
            raise ValueError("Unknown identity")
        await self.runtime.async_command("select_identity", {"point_id": self.id_, "identity_id": identity["id"]})
