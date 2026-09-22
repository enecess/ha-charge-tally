"""Ledger settings and explicit, previewed archive maintenance."""
import sqlite3

import voluptuous as vol

from homeassistant.config_entries import OptionsFlow
from homeassistant.helpers import config_validation as cv, selector
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN


def _objects(items):
    return selector.SelectSelector(selector.SelectSelectorConfig(options=[
        {"value": item["id"], "label": f"{item['name']} ({item['id'][:8]})"} for item in items
    ]))


class LedgerOptionsFlow(OptionsFlow):
    """Keep destructive actions separate from ordinary currency settings."""

    def __init__(self):
        self._original_currency = None
        self._archive_kind = None
        self._archive_preview = None
        self._archive_result = None

    def _runtime(self):
        runtime = getattr(self.config_entry, "runtime_data", None)
        if runtime is None or runtime._closed or runtime._closing:
            raise ValueError("runtime_unavailable")
        return runtime

    async def async_step_init(self, user_input=None):
        try:
            self._runtime()
        except ValueError:
            return self.async_abort(reason="runtime_unavailable")
        return self.async_show_menu(step_id="init", menu_options=["currency", "archive"])

    async def async_step_currency(self, user_input=None):
        entry = self.config_entry
        errors = {}
        try:
            runtime = self._runtime()
            if not await runtime.async_currency_change_allowed():
                return await self.async_step_locked()
            if self._original_currency is None:
                self._original_currency = entry.data["currency"]
            if user_input is not None:
                try:
                    currency = cv.currency(user_input["currency"].strip().upper())
                except (vol.Invalid, KeyError, AttributeError):
                    errors["base"] = "invalid_currency"
                else:
                    await runtime.async_change_currency(currency, self._original_currency)
                    return self.async_create_entry(title="", data=dict(entry.options))
        except ValueError as err:
            if str(err) == "currency_locked":
                return await self.async_step_locked()
            if str(err) in ("config_changed", "runtime_unavailable"):
                return self.async_abort(reason=str(err))
            raise
        except (OSError, sqlite3.Error):
            errors["base"] = "save_failed"
        return self.async_show_form(step_id="currency", data_schema=vol.Schema({
            vol.Required("currency", default=entry.data["currency"]): selector.TextSelector(),
        }), description_placeholders={"currency": entry.data["currency"]}, errors=errors)

    async def async_step_locked(self, user_input=None):
        if user_input is not None:
            return await self.async_step_init()
        return self.async_show_form(step_id="locked", data_schema=vol.Schema({}),
                                    description_placeholders={"currency": self.config_entry.data["currency"]})

    async def async_step_archive(self, user_input=None):
        return self.async_show_menu(step_id="archive", menu_options=["archive_points", "archive_identities"])

    async def async_step_archive_points(self, user_input=None):
        self._archive_kind = "point"
        return await self.async_step_archive_select(user_input)

    async def async_step_archive_identities(self, user_input=None):
        self._archive_kind = "identity"
        return await self.async_step_archive_select(user_input)

    def _archive_error(self, err):
        reason = str(err)
        if reason not in {"runtime_unavailable", "archive_not_found", "archive_configured",
                          "archive_busy", "archive_stale", "archive_target"}:
            raise err
        return self.async_abort(reason=reason)

    async def async_step_archive_select(self, user_input=None):
        errors = {}
        try:
            runtime = self._runtime()
            catalog = await runtime.async_archive_catalog()
            items = catalog["points" if self._archive_kind == "point" else "identities"]
            if not items:
                return await self.async_step_archive_empty()
            if user_input is not None:
                object_id = user_input.get("object_id")
                if object_id not in {item["id"] for item in items}:
                    return self.async_abort(reason="archive_not_found")
                self._archive_preview = await runtime.async_archive_preview(self._archive_kind, object_id)
                if self._archive_kind == "identity" and self._archive_preview["record_count"]:
                    return await self.async_step_archive_target()
                return await self.async_step_archive_confirm()
        except ValueError as err:
            return self._archive_error(err)
        except (OSError, sqlite3.Error):
            errors["base"] = "archive_failed"
            items = []
        return self.async_show_form(step_id="archive_select", data_schema=vol.Schema({
            vol.Required("object_id"): _objects(items),
        }), errors=errors)

    async def async_step_archive_empty(self, user_input=None):
        if user_input is not None:
            return await self.async_step_init()
        return self.async_show_form(step_id="archive_empty", data_schema=vol.Schema({}))

    async def async_step_archive_target(self, user_input=None):
        errors = {}
        try:
            runtime = self._runtime()
            catalog = await runtime.async_archive_catalog()
            targets = catalog["targets"]
            if user_input is not None:
                target = user_input.get("target_identity_id")
                if target not in {item["id"] for item in targets}:
                    errors["base"] = "archive_target"
                else:
                    self._archive_preview = await runtime.async_archive_preview(
                        "identity", self._archive_preview["id"], target,
                    )
                    return await self.async_step_archive_confirm()
        except ValueError as err:
            return self._archive_error(err)
        except (OSError, sqlite3.Error):
            errors["base"] = "archive_failed"
            targets = []
        return self.async_show_form(step_id="archive_target", data_schema=vol.Schema({
            vol.Required("target_identity_id", default="unassigned"): _objects(targets),
        }), description_placeholders={"name": self._archive_preview["name"],
                                      "records": str(self._archive_preview["record_count"])}, errors=errors)

    async def async_step_archive_confirm(self, user_input=None):
        preview = self._archive_preview
        errors = {}
        if user_input is not None:
            if user_input.get("confirm") is not True:
                errors["base"] = "confirm_required"
            else:
                try:
                    self._archive_result = await self._runtime().async_archive_delete(
                        preview["kind"], preview["id"], preview["fingerprint"],
                        preview.get("target_identity_id"),
                    )
                except ValueError as err:
                    return self._archive_error(err)
                except (OSError, sqlite3.Error):
                    errors["base"] = "archive_failed"
                else:
                    return await self.async_step_archive_done()
        action = "delete_point" if preview["kind"] == "point" else (
            "transfer_identity" if preview["record_count"] else "delete_identity"
        )
        translations = await async_get_translations(
            self.hass, self.context.get("language", self.hass.config.language), "selector", {DOMAIN},
        )
        end = (translations[f"component.{DOMAIN}.selector.archive_time.options.unfinished"]
               if preview["active_count"] else preview.get("end") or "—")
        return self.async_show_form(step_id="archive_confirm", data_schema=vol.Schema({
            vol.Required("confirm", default=False): selector.BooleanSelector(),
        }), description_placeholders={
            "name": preview["name"], "records": str(preview["record_count"]),
            "active": str(preview["active_count"]),
            "voided": str(preview["void_count"]), "revisions": str(preview["revision_count"]),
            "start": preview.get("start") or "—", "end": end,
            "energy": str(preview["energy_kwh"]), "cost": str(preview["known_cost"]),
            "currency": preview["currency"], "target": preview.get("target_name") or "—",
            "operation": translations[f"component.{DOMAIN}.selector.archive_action.options.{action}"],
        }, errors=errors)

    async def async_step_archive_done(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=dict(self.config_entry.options))
        result = self._archive_result
        return self.async_show_form(step_id="archive_done", data_schema=vol.Schema({}),
                                    description_placeholders={
            "name": self._archive_preview["name"],
            "deleted": str(result["record_count"] if result["kind"] == "point" else 0),
            "transferred": str(result["transferred_count"]),
        })
