"""Per-point pending and future record identity selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity

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
            [IdentitySelect(runtime, sub)] if sub.subentry_type == "point" else []
        ),
    )


class IdentitySelect(TallyEntity, SelectEntity):
    """Choose the identity for a pending start or a future record."""

    def __init__(self, runtime: Runtime, sub: ConfigSubentry) -> None:
        super().__init__(
            runtime,
            sub.subentry_id,
            "identity",
            sub.data["name"] + " Identity",
            sub.data["name"],
        )

    @property
    def options(self) -> list[str]:
        """Return active identity names from the current snapshot."""
        return [
            i["name"]
            for i in self.runtime.snapshot["identities"]
            if i.get("active", True)
        ]

    @property
    def current_option(self) -> str | None:
        """Return the point's selected identity, if available."""
        return next(
            (
                i["name"]
                for i in self.runtime.snapshot["identities"]
                if self.point and i["id"] == self.point["selected_identity_id"]
            ),
            None,
        )

    async def async_select_option(self, option: str) -> None:
        """Persist an active identity selection through the runtime."""
        identity = next(
            (
                i
                for i in self.runtime.snapshot["identities"]
                if i["name"] == option and i.get("active", True)
            ),
            None,
        )
        if identity is None:
            raise ValueError("Unknown identity")
        await self.runtime.async_select_identity(self.id_, identity["id"])
