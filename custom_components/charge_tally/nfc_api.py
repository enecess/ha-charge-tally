"""Authenticated management and stable-identity action adapters for NFC links."""

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.components import websocket_api
from homeassistant.core import SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError, Unauthorized

from .api import ID, REV, authorize, current_runtime


@callback
def async_register(hass):
    """Expose identity selection even while the ledger is unavailable."""
    async_register_management(hass)
    if hass.services.has_service("charge_tally", "select_identity"):
        return

    async def select_identity(call):
        user = (
            await hass.auth.async_get_user(call.context.user_id)
            if call.context.user_id
            else None
        )
        if call.context.user_id and (user is None or not user.is_active):
            raise Unauthorized()
        runtime = current_runtime(hass)
        data = call.data

        def guard():
            authorize(runtime, user, data["point_id"], POLICY_CONTROL)
            if "rule_id" in data:
                runtime.nfc.assert_selection(
                    data["rule_id"],
                    data["rule_version"],
                    data["point_id"],
                    data["identity_id"],
                )

        try:
            return await runtime.async_select_identity(
                data["point_id"], data["identity_id"], authorize=guard
            )
        except ValueError as err:
            code = str(err)
            if code not in {
                "not_applied",
                "invalid_reference",
                "runtime_unavailable",
                "rule_missing",
            }:
                code = "invalid_request"
            raise ServiceValidationError(
                translation_domain="charge_tally", translation_key=code
            ) from err

    hass.services.async_register(
        "charge_tally",
        "select_identity",
        select_identity,
        schema=vol.Schema(
            {
                vol.Required("point_id"): ID,
                vol.Required("identity_id"): ID,
                vol.Inclusive("rule_id", "managed"): ID,
                vol.Inclusive("rule_version", "managed"): REV,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )


@callback
def async_register_management(hass):
    """Keep rule management separate from ordinary point access."""
    if hass.data.get("charge_tally_nfc_api_registered"):
        return
    schemas = {
        "catalog": {},
        "list": {},
        "prepare": {
            vol.Required("kind"): vol.In(
                ("create", "update", "restore", "recreate", "delete")
            ),
            vol.Required("rule_id"): vol.Any(None, ID),
            vol.Required("draft"): vol.Any(None, dict),
            vol.Required("expected_revision"): vol.Any(None, REV),
            vol.Required("operation_id"): ID,
        },
        "inspect": {
            vol.Required("rule_id"): ID,
            vol.Required("observed_config"): vol.Any(None, dict),
        },
        "confirm": {
            vol.Required("operation_id"): ID,
            vol.Required("observed_config"): vol.Any(None, dict),
        },
        "cancel": {
            vol.Required("operation_id"): ID,
            vol.Required("observed_config"): vol.Any(None, dict),
        },
    }
    for command, schema in schemas.items():

        async def handle(hass, connection, msg, command=command):
            def admin():
                if not connection.user.is_active or not connection.user.is_admin:
                    raise Unauthorized()

            try:
                admin()
                entry = hass.config_entries.async_get_entry(msg["entry_id"])
                runtime = getattr(entry, "runtime_data", None)
                if (
                    entry is None
                    or entry.domain != "charge_tally"
                    or runtime is None
                    or runtime._closing
                    or runtime._closed
                ):
                    raise ValueError("runtime_unavailable")
                manager = runtime.nfc
                payload = {
                    k: v for k, v in msg.items() if k not in ("id", "type", "entry_id")
                }
                if command in ("prepare", "confirm", "cancel"):
                    payload["authorize"] = admin
                result = await getattr(manager, f"async_{command}")(**payload)
                admin()
                connection.send_result(msg["id"], result)
            except Unauthorized:
                connection.send_error(
                    msg["id"], "unauthorized", "Administrator access required"
                )
            except (ValueError, KeyError, TypeError) as err:
                code = str(err)
                if code not in {
                    "runtime_unavailable",
                    "rule_missing",
                    "conflict",
                    "pending",
                    "invalid_reference",
                    "duplicate_rule",
                    "duplicate_device",
                    "empty_rule",
                    "invalid_storage",
                }:
                    code = "invalid_request"
                connection.send_error(
                    msg["id"], code, "The NFC operation could not be applied"
                )
            except OSError:
                connection.send_error(
                    msg["id"], "save_failed", "NFC configuration could not be saved"
                )

        wrapped = websocket_api.websocket_command(
            {
                vol.Required("type"): f"charge_tally/nfc/{command}",
                vol.Required("entry_id"): ID,
                **schema,
            }
        )(websocket_api.async_response(handle))
        websocket_api.async_register_command(hass, wrapped)
    hass.data["charge_tally_nfc_api_registered"] = True
