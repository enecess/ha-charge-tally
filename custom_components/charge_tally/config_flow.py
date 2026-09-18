"""Native Home Assistant configuration for the ledger and its subentries."""
from copy import deepcopy
import re
import sqlite3

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlow, ConfigSubentryFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import config_validation as cv, selector
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN, INPUT_MODES, NAME, PERIODS, RESTRICTED_POINT_FIELDS
from .config_validation import validate_detection, validate_identity_name, validate_name, validate_point, validate_price
from .core.units import decimal_value, price_per_kwh
from .ledger import retained_currency


_NEXT_SUBENTRY_FLOW = getattr(getattr(config_entries, "FlowType", None), "CONFIG_SUBENTRIES_FLOW", None)


def _choice(options, *, multiple=False, translation_key=None):
    config = {"options": list(options), "multiple": multiple}
    if translation_key is not None:
        config["translation_key"] = translation_key
    return selector.SelectSelector(selector.SelectSelectorConfig(**config))


def _number(default_min=None):
    config = {"mode": selector.NumberSelectorMode.BOX}
    if default_min is not None:
        config["min"] = default_min
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


def _entity(device_class=None):
    config = {"domain": "sensor"}
    if device_class:
        config["device_class"] = device_class
    return selector.EntitySelector(selector.EntitySelectorConfig(**config))


class ChargeTallyConfigFlow(ConfigFlow, domain=DOMAIN):
    """One currency and one persistent ledger per Home Assistant instance."""
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return LedgerOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry):
        return {"point": PointSubentryFlow, "identity": IdentitySubentryFlow}

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors = {}
        try:
            retained = await self.hass.async_add_executor_job(retained_currency, self.hass.config.path("charge_tally/ledger.sqlite3"))
        except ValueError as err:
            return self.async_abort(reason=str(err))
        if user_input is not None:
            try:
                currency = cv.currency(user_input["currency"].strip().upper())
            except (vol.Invalid, KeyError, AttributeError):
                errors["base"] = "invalid_currency"
            else:
                if retained is not None and retained != currency:
                    errors["base"] = "currency_mismatch"
                else:
                    await self.async_set_unique_id(DOMAIN)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title=NAME, data={"currency": currency})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required("currency", default=retained or self.hass.config.currency): selector.TextSelector(),
        }), errors=errors)

    async def async_on_create_entry(self, result):
        if _NEXT_SUBENTRY_FLOW is None:
            return result
        next_result = await self.hass.config_entries.subentries.async_init(
            (result["result"].entry_id, "point"), context={"source": "user"},
        )
        result["next_flow"] = (_NEXT_SUBENTRY_FLOW, next_result["flow_id"])
        return result


class LedgerOptionsFlow(OptionsFlow):
    """Expose ledger settings without relabeling historical amounts."""

    def __init__(self):
        self._original_currency = None

    async def async_step_init(self, user_input=None):
        entry = self.config_entry
        runtime = getattr(entry, "runtime_data", None)
        if runtime is None:
            return self.async_abort(reason="runtime_unavailable")
        errors = {}
        try:
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
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required("currency", default=entry.data["currency"]): selector.TextSelector(),
        }), description_placeholders={"currency": entry.data["currency"]}, errors=errors)

    async def async_step_locked(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=dict(self.config_entry.options))
        return self.async_show_form(step_id="locked", data_schema=vol.Schema({}),
                                    description_placeholders={"currency": self.config_entry.data["currency"]})


class IdentitySubentryFlow(ConfigSubentryFlow):
    """Maintain shared identities; HA subentry IDs remain stable on rename."""
    async def async_step_reconfigure(self, user_input=None):
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input=None):
        entry = self.hass.config_entries.async_get_known_entry(self.handler[0])
        editing = self._get_reconfigure_subentry() if self.source == "reconfigure" else None
        defaults = editing.data if editing else {"name": "", "enabled": True}
        errors = {}
        if user_input is not None:
            try:
                name = validate_identity_name(user_input.get("name"))
                enabled = user_input.get("enabled", True)
                if not isinstance(enabled, bool):
                    raise ValueError("invalid_identity")
                if any(sub.subentry_type == "identity" and sub != editing and sub.data["name"].casefold() == name.casefold() for sub in entry.subentries.values()):
                    raise ValueError("duplicate_name")
                data = {"name": name, "enabled": enabled}
            except ValueError as err:
                errors["base"] = str(err)
            else:
                if editing:
                    return self.async_update_and_abort(entry, editing, title=name, data=data)
                return self.async_create_entry(title=name, data=data)
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required("name", default=defaults["name"]): selector.TextSelector(),
            vol.Required("enabled", default=defaults["enabled"]): selector.BooleanSelector(),
        }), errors=errors)


class PointSubentryFlow(ConfigSubentryFlow):
    """Collect input, optional detection, pricing and period settings in steps."""
    def __init__(self):
        self._data = {}
        self._original = None
        self._currency = None
        self._rows = []
        self._row_index = None

    async def async_step_reconfigure(self, user_input=None):
        self._original = deepcopy(dict(self._get_reconfigure_subentry().data))
        self._data = deepcopy(self._original)
        self._rows = deepcopy(self._data.get("price", {}).get("schedule", []))
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input=None):
        if self._currency is None:
            self._currency = self.hass.config_entries.async_get_known_entry(self.handler[0]).data["currency"]
        errors = {}
        if user_input is not None:
            try:
                name = validate_name(user_input.get("name"))
                mode = user_input.get("input_mode")
                if mode not in INPUT_MODES:
                    raise ValueError("invalid_input_mode")
            except ValueError as err:
                errors["base"] = str(err)
            else:
                self._data.update(name=name, input_mode=mode)
                return await self.async_step_input()
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required("name", default=self._data.get("name", "")): selector.TextSelector(),
            vol.Required("input_mode", default=self._data.get("input_mode", "energy")): _choice(INPUT_MODES, translation_key="input_mode"),
        }), errors=errors)

    def _validate_sources(self, data):
        for field in ("energy_entity", "power_entity"):
            if field not in data:
                continue
            state = self.hass.states.get(data[field])
            if state is None or not data[field].startswith("sensor."):
                raise ValueError("invalid_source")
            unit = state.attributes.get("unit_of_measurement")
            if field == "energy_entity":
                if unit not in ("Wh", "kWh", "MWh") or state.attributes.get("state_class") not in ("total", "total_increasing"):
                    raise ValueError("invalid_energy_source")
            elif unit not in ("W", "kW"):
                raise ValueError("invalid_power_source")
            if state.state not in ("unknown", "unavailable"):
                try:
                    decimal_value(state.state, nonnegative=True)
                except ValueError as err:
                    raise ValueError("invalid_source") from err

    async def async_step_input(self, user_input=None):
        mode = self._data["input_mode"]
        errors = {}
        if user_input is not None:
            candidate = deepcopy(self._data)
            candidate.pop("energy_entity", None)
            candidate.pop("power_entity", None)
            values = dict(user_input.get("measurement", {}))
            enabled = values.pop("detection_enabled", False) if mode != "energy" else False
            candidate.update(values)
            try:
                for field, required in (("energy_entity", mode != "power"), ("power_entity", mode != "energy")):
                    if required and field not in candidate:
                        raise ValueError("invalid_source")
                    if not required:
                        candidate.pop(field, None)
                self._validate_sources(candidate)
                if decimal_value(candidate.get("max_gap_seconds", 600)) <= 0:
                    raise ValueError("invalid_gap")
            except ValueError as err:
                errors["base"] = str(err) if str(err).startswith("invalid_") else "invalid_gap"
            else:
                self._data = candidate
                self._data["detection"] = {**self._data.get("detection", {}), "enabled": enabled}
                if enabled:
                    return await self.async_step_detection()
                self._data["detection"] = {"enabled": False}
                return await self.async_step_price()
        fields = {}
        for field, required, device in (("energy_entity", mode != "power", "energy"), ("power_entity", mode != "energy", "power")):
            if required:
                marker = vol.Required(field, default=self._data[field]) if field in self._data else vol.Required(field)
                fields[marker] = _entity(device)
        fields[vol.Required("resetting", default=self._data.get("resetting", True))] = selector.BooleanSelector()
        fields[vol.Required("max_gap_seconds", default=self._data.get("max_gap_seconds", 600))] = _number(1)
        if mode != "energy":
            fields[vol.Required("detection_enabled", default=self._data.get("detection", {}).get("enabled", False))] = selector.BooleanSelector()
        return self.async_show_form(step_id="input", data_schema=vol.Schema({
            vol.Required("measurement"): section(vol.Schema(fields)),
        }), errors=errors)

    async def async_step_detection(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                self._data["detection"] = validate_detection({**user_input, "enabled": True})
            except ValueError:
                errors["base"] = "invalid_detection"
            else:
                return await self.async_step_price()
        defaults = self._data.get("detection", {})
        fields = {}
        for key, default in (("start_w", None), ("end_w", None), ("start_seconds", 30), ("end_seconds", 300)):
            value = defaults.get(key, default)
            marker = vol.Required(key, default=float(value)) if value is not None else vol.Required(key)
            fields[marker] = _number(0)
        return self.async_show_form(step_id="detection", data_schema=vol.Schema(fields), errors=errors)

    async def async_step_price(self, user_input=None):
        if user_input is not None:
            mode = user_input.get("mode")
            if mode in ("static", "dynamic", "tou"):
                self._data["price"] = {**self._data.get("price", {}), "mode": mode}
                return await getattr(self, f"async_step_{mode}")()
        return self.async_show_form(step_id="price", data_schema=vol.Schema({
            vol.Required("mode", default=self._data.get("price", {}).get("mode", "static")): _choice(("static", "dynamic", "tou"), translation_key="price_mode"),
        }))

    async def async_step_static(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                self._data["price"] = validate_price({"mode": "static", **user_input})
            except ValueError:
                errors["base"] = "invalid_price"
            else:
                return await self.async_step_finish()
        return self.async_show_form(step_id="static", data_schema=vol.Schema({
            vol.Required("value", default=self._data["price"].get("value", "")): selector.TextSelector(),
        }), description_placeholders={"currency": self.hass.config_entries.async_get_known_entry(self.handler[0]).data["currency"]}, errors=errors)

    def _dynamic_price(self, values):
        state = self.hass.states.get(values.get("entity_id", ""))
        if state is None:
            raise ValueError("invalid_source")
        source_unit = state.attributes.get("unit_of_measurement")
        unit = source_unit or values.get("unit")
        try:
            price_per_kwh(0, unit, self.hass.config_entries.async_get_known_entry(self.handler[0]).data["currency"])
            if source_unit and values.get("unit") and values["unit"] != source_unit:
                raise ValueError
        except ValueError as err:
            raise ValueError("invalid_price_unit") from err
        return validate_price({"mode": "dynamic", "entity_id": values["entity_id"], "unit": unit})

    async def async_step_dynamic(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                self._data["price"] = self._dynamic_price(user_input)
            except ValueError as err:
                errors["base"] = str(err)
            else:
                return await self.async_step_finish()
        currency = self.hass.config_entries.async_get_known_entry(self.handler[0]).data["currency"]
        fields = {vol.Required("entity_id"): _entity(), vol.Optional("unit"): _choice([f"{currency}/{unit}" for unit in ("Wh", "kWh", "MWh")])}
        schema = self.add_suggested_values_to_schema(vol.Schema(fields), self._data["price"])
        return self.async_show_form(step_id="dynamic", data_schema=schema, errors=errors)

    async def async_step_tou(self, user_input=None):
        errors = {}
        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                self._row_index = None
                return await self.async_step_tou_row()
            if action in ("edit", "remove"):
                try:
                    index = int(user_input["row"])
                    if not 0 <= index < len(self._rows):
                        raise ValueError
                except (KeyError, ValueError, TypeError):
                    errors["base"] = "invalid_row"
                else:
                    if action == "remove":
                        self._rows.pop(index)
                    else:
                        self._row_index = index
                        return await self.async_step_tou_row()
            elif action == "finish":
                try:
                    self._data["price"] = validate_price({"mode": "tou", "schedule": self._rows})
                except ValueError:
                    errors["base"] = "invalid_schedule"
                else:
                    return await self.async_step_finish()
        fields = {vol.Required("action"): _choice(("add", "edit", "remove", "finish") if self._rows else ("add", "finish"), translation_key="schedule_action")}
        if self._rows:
            fields[vol.Optional("row")] = _choice([{"value": str(i), "label": f"{row['start']}–{row['end']}: {row['price']}"} for i, row in enumerate(self._rows)])
        summary = "\n".join(f"{row['start']}–{row['end']}: {row['price']}" for row in self._rows) or "—"
        return self.async_show_form(step_id="tou", data_schema=vol.Schema(fields), description_placeholders={"schedule": summary}, errors=errors)

    async def async_step_tou_row(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                row = {key: user_input[key] for key in ("start", "end", "price")}
                for key in ("start", "end"):
                    pattern = r"(?:[01]\d|2[0-3]):[0-5]\d" + (r"|24:00" if key == "end" else "")
                    if not re.fullmatch(pattern, row[key]):
                        raise ValueError
                if row["start"] == row["end"]:
                    raise ValueError
                row["price"] = str(decimal_value(row["price"]))
            except (ValueError, KeyError, TypeError):
                errors["base"] = "invalid_row"
            else:
                if self._row_index is None:
                    self._rows.append(row)
                else:
                    self._rows[self._row_index] = row
                return await self.async_step_tou()
        defaults = self._rows[self._row_index] if self._row_index is not None else {"start": "00:00", "end": "24:00", "price": ""}
        return self.async_show_form(step_id="tou_row", data_schema=vol.Schema({vol.Required(key, default=value): selector.TextSelector() for key, value in defaults.items()}), errors=errors)

    async def async_step_finish(self, user_input=None):
        errors = {}
        if user_input is not None:
            entry = self.hass.config_entries.async_get_known_entry(self.handler[0])
            if entry.data["currency"] != self._currency:
                return self.async_abort(reason="config_changed")
            editing = self._get_reconfigure_subentry() if self.source == "reconfigure" else None
            existing = [dict(sub.data) for sub in entry.subentries.values() if sub.subentry_type == "point" and sub != editing]
            try:
                data = validate_point({**self._data, **user_input}, existing)
                self._validate_sources(data)
                if data["price"]["mode"] == "dynamic":
                    data["price"] = self._dynamic_price(data["price"])
            except ValueError as err:
                errors["base"] = str(err)
            else:
                if editing:
                    if dict(editing.data) != self._original:
                        return self.async_abort(reason="config_changed")
                    if any(editing.data.get(key) != data.get(key) for key in RESTRICTED_POINT_FIELDS):
                        runtime = getattr(entry, "runtime_data", None)
                        guard = getattr(runtime, "async_config_guard", None)
                        if guard is None:
                            return self.async_abort(reason="runtime_unavailable")
                        if not await guard(editing.subentry_id, dict(editing.data), data):
                            return self.async_abort(reason="point_busy")
                    latest = entry.subentries.get(editing.subentry_id)
                    if latest is None or dict(latest.data) != self._original:
                        return self.async_abort(reason="config_changed")
                    try:
                        data = validate_point(data, [dict(sub.data) for sub in entry.subentries.values()
                                                    if sub.subentry_type == "point" and sub != latest])
                    except ValueError as err:
                        errors["base"] = str(err)
                    else:
                        return self.async_update_and_abort(entry, latest, title=data["name"], data=data)
                else:
                    return self.async_create_entry(title=data["name"], data=data)
        translations = await async_get_translations(
            self.hass, self.context.get("language", self.hass.config.language), "selector", {DOMAIN}
        )
        prefix = f"component.{DOMAIN}.selector."
        input_label = translations[prefix + f"input_mode.options.{self._data['input_mode']}"]
        price_label = translations[prefix + f"price_mode.options.{self._data['price']['mode']}"]
        summary = f"{self._data['name']} · {input_label} · {price_label}"
        return self.async_show_form(step_id="finish", data_schema=vol.Schema({
            vol.Required("periods", default=self._data.get("periods", list(PERIODS))): _choice(PERIODS, multiple=True, translation_key="periods"),
        }), description_placeholders={"summary": summary}, errors=errors)
