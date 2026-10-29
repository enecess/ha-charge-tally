"""Register the local card directory and a dashboard resource."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import callback
from homeassistant.setup import async_setup_component

if TYPE_CHECKING:
    from homeassistant.core import Event, HomeAssistant


class CardResource(TypedDict):
    """Describe the card resource and whether it needs manual registration."""

    url: str
    type: str
    manual: bool


CARD_URL = "/charge_tally/charge-tally-card.js?v=0.1.2-11"
NFC_URL = "/charge_tally/nfc-panel.js?v=0.1.2-11"


async def async_register(hass: HomeAssistant) -> CardResource:
    """Register static assets and update the storage dashboard resource."""
    lock = hass.data.setdefault("charge_tally_frontend_lock", asyncio.Lock())
    async with lock:
        if not hass.data.get("charge_tally_nfc_panel_registered"):
            await async_register_panel(
                hass,
                "charge-tally-nfc",
                "charge-tally-nfc-panel",
                module_url=NFC_URL,
                require_admin=True,
            )
            hass.data["charge_tally_nfc_panel_registered"] = True
        if hass.http is not None and not hass.data.get(
            "charge_tally_static_registered"
        ):
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(
                        "/charge_tally",
                        str(Path(__file__).parent / "www"),
                        cache_headers=True,
                    )
                ]
            )
            hass.data["charge_tally_static_registered"] = True
        lovelace = hass.data.get(LOVELACE_DATA)
        mode = getattr(lovelace, "resource_mode", getattr(lovelace, "mode", None))
        manual = mode != "storage"
        if not manual:
            resources = lovelace.resources
            await resources.async_get_info()
            matching = next(
                (
                    item
                    for item in resources.async_items()
                    if item["url"].split("?", 1)[0] == CARD_URL.split("?", 1)[0]
                ),
                None,
            )
            if matching is None:
                await resources.async_create_item(
                    {"url": CARD_URL, "res_type": "module"}
                )
            elif matching["url"] != CARD_URL or matching["type"] != "module":
                await resources.async_update_item(
                    matching["id"], {"url": CARD_URL, "res_type": "module"}
                )
        return {"url": CARD_URL, "type": "module", "manual": manual}


async def async_setup(hass: HomeAssistant) -> CardResource:
    """Register the card and retry registration as frontend components load."""
    if hass.http is None:
        await async_setup_component(hass, "http", {})
    if not hass.data.get("charge_tally_frontend_listener"):

        @callback
        def loaded(event: Event) -> None:
            """Refresh the resource after HTTP or Lovelace becomes available."""
            if event.data.get("component") in ("http", "lovelace"):
                hass.async_create_task(async_register(hass))

        hass.data["charge_tally_frontend_listener"] = hass.bus.async_listen(
            EVENT_COMPONENT_LOADED, loaded
        )
    return await async_register(hass)
