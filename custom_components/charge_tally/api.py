"""Authenticated public commands and point-scoped subscriptions."""
from copy import deepcopy
from datetime import datetime, UTC
from decimal import Decimal, InvalidOperation
from hashlib import sha256

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_READ, POLICY_CONTROL
from homeassistant.components import websocket_api
from homeassistant.core import SupportsResponse, callback
from homeassistant.exceptions import Unauthorized, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect

DOMAIN = "charge_tally"
ID = vol.All(str, vol.Length(min=1, max=128))


def integer(value):
    if type(value) is not int:
        raise vol.Invalid("Expected an integer")
    return value


def date(value):
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
        if parsed is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(UTC).isoformat()
    except (ValueError, TypeError, OverflowError):
        raise vol.Invalid("Expected a timezone-aware ISO datetime") from None


def amount(value):
    try:
        if not isinstance(value, str) or len(value) > 100 or not Decimal(value).is_finite():
            raise ValueError
        return value
    except (ValueError, InvalidOperation):
        raise vol.Invalid("Expected a finite decimal string") from None


REV = vol.All(integer, vol.Range(min=1))
SCOPE = {vol.Optional("point_id"): ID}
FILTER = {**SCOPE, vol.Optional("identity_id"): ID}
WRITE = {vol.Required("request_id"): ID}
SCHEMAS = {
    "snapshot": SCOPE,
    "subscribe": SCOPE,
    "query": {**FILTER, vol.Required("start"): date, vol.Required("end"): date},
    "records": {**FILTER, vol.Optional("record_id"): ID, vol.Optional("offset", default=0): vol.All(integer, vol.Range(min=0)),
                vol.Optional("limit", default=50): vol.All(integer, vol.Range(min=1, max=100))},
    "preview": {**FILTER, vol.Optional("record_id"): ID, vol.Optional("expected_revision"): REV,
                vol.Optional("start"): date, vol.Optional("end"): date,
                vol.Optional("energy_kwh"): vol.All(amount, lambda v: v if Decimal(v) >= 0 else _invalid()),
                vol.Optional("cost"): vol.Any(None, amount), vol.Optional("note"): vol.All(str, vol.Length(max=2000))},
    "commit": {**WRITE, vol.Required("token"): ID, vol.Optional("expected_revision"): REV},
    "reassign": {**WRITE, vol.Required("record_id"): ID, vol.Required("identity_id"): ID, vol.Required("expected_revision"): REV},
    "void": {**WRITE, vol.Required("record_id"): ID, vol.Required("expected_revision"): REV},
}


def _invalid():
    raise vol.Invalid("Energy must be nonnegative")


def current_runtime(hass):
    runtimes = hass.data.get(DOMAIN, {})
    if not runtimes:
        raise ServiceValidationError("Charge Tally is not loaded")
    return next(iter(runtimes.values()))


def anchor_for(runtime, point_id):
    registry = er.async_get(runtime.hass)
    unique = f"{runtime.entry.entry_id}:{point_id}:identity"
    entity_id = registry.async_get_entity_id("select", DOMAIN, unique)
    anchor = registry.async_get(entity_id) if entity_id else None
    if (point_id not in runtime.points or anchor is None or anchor.disabled
        or anchor.config_entry_id != runtime.entry.entry_id or anchor.config_subentry_id != point_id
        or anchor.unique_id != unique or anchor.platform != DOMAIN or anchor.domain != "select"):
        return None
    return anchor.entity_id


def authorize(runtime, user, point_id, policy):
    if user is None:
        return
    if not user.is_active:
        raise Unauthorized()
    if user.is_admin:
        return
    entity_id = anchor_for(runtime, point_id)
    if entity_id is None or not user.permissions.check_entity(entity_id, policy):
        raise Unauthorized()


async def allowed_points(runtime, user, requested=None):
    snapshot = runtime.snapshot
    ids = [p["id"] for p in snapshot["points"] + snapshot.get("archived_points", [])]
    allowed = []
    for point_id in ids:
        try:
            authorize(runtime, user, point_id, POLICY_READ)
        except Unauthorized:
            continue
        allowed.append(point_id)
    if requested is not None:
        if requested not in allowed:
            raise Unauthorized()
        return [requested]
    return allowed


async def public_snapshot(runtime, user, point_id=None):
    result = await scoped_read(runtime, user, point_id, runtime.async_snapshot)
    result.pop("revision", None)
    result.pop("records", None)
    if not result["points"] and not result.get("archived_points"):
        result["identities"] = []
    return result


async def scoped_read(runtime, user, requested, read):
    while True:
        allowed = await allowed_points(runtime, user, requested)
        result = await read(allowed)
        if allowed == await allowed_points(runtime, user, requested):
            return result


async def execute(hass, user, command, payload):
    runtime = current_runtime(hass)
    data = dict(payload)
    if command == "snapshot":
        return await public_snapshot(runtime, user, data.get("point_id"))
    if command in ("query", "records"):
        if command == "query" and datetime.fromisoformat(data["start"]) >= datetime.fromisoformat(data["end"]):
            raise vol.Invalid("End must follow start")
        try:
            return await scoped_read(runtime, user, data.get("point_id"),
                lambda ids: runtime.async_query("record" if data.get("record_id") else "summary" if command == "query" else command,
                    data, point_ids=ids))
        except ValueError:
            if data.get("record_id"):
                raise Unauthorized() from None
            raise
    principal = user.id if user else "system"
    if data.get("record_id"):
        try:
            detail = await runtime.async_query("record", {"record_id": data["record_id"]},
                point_ids=await allowed_points(runtime, user))
        except ValueError:
            raise Unauthorized() from None
        point_id = detail["record"]["point_id"]
        if data.get("point_id", point_id) != point_id:
            raise Unauthorized()
    elif command == "commit":
        binding = await runtime.async_api_metadata("preview", data["token"])
        if not binding or binding["principal"] != principal:
            raise Unauthorized()
        point_id = binding["point_id"]
        if data.get("expected_revision") != binding.get("expected_revision"):
            raise ValueError("Revision conflict")
    else:
        point_id = data.get("point_id")
    if not point_id:
        raise vol.Invalid("A point or record is required")
    authorize(runtime, user, point_id, POLICY_CONTROL)
    if command == "preview":
        authorize(runtime, user, point_id, POLICY_READ)
        if not data.get("record_id") and not all(k in data for k in ("point_id", "identity_id", "start", "end")):
            raise vol.Invalid("New history requires point, identity, start and end")
        result = await runtime.async_command("preview", data)
        await runtime.async_bind_preview(result["token"], principal, point_id, result["expected_revision"])
        authorize(runtime, user, point_id, POLICY_READ)
        authorize(runtime, user, point_id, POLICY_CONTROL)
        result.pop("basis_version", None)
        result.pop("basis_fingerprint", None)
        result.pop("basis_dependencies", None)
        return result
    if command == "start" and point_id not in runtime.points:
        raise Unauthorized()
    return await runtime.async_public_command(command, data, principal,
        lambda: authorize(runtime, user, point_id, POLICY_CONTROL))


def error_code(error):
    message = str(error).lower()
    return "stale_preview" if "stale" in message else "overlap" if "overlap" in message else "conflict" if "revision" in message or "request id" in message else "invalid_request"


async def subscribe(hass, connection, msg):
    runtime = current_runtime(hass)
    await allowed_points(runtime, connection.user, msg.get("point_id"))
    closed = False
    previous = None
    generation = 0
    async def publish():
        nonlocal previous, generation
        if closed:
            return
        try:
            result = await public_snapshot(runtime, connection.user, msg.get("point_id"))
        except Unauthorized:
            result = {"points": [], "archived_points": [], "identities": [], "summary": {}}
        if not closed and result != previous:
            previous = deepcopy(result)
            generation += 1
            connection.send_event(msg["id"], {**result, "generation": generation})
    @callback
    def updated():
        if not closed:
            hass.async_create_task(publish())
    unsub = async_dispatcher_connect(hass, runtime.update_signal, updated)
    @callback
    def cancel():
        nonlocal closed, unsub
        if not closed:
            closed = True
            unsub()
            unsub = None
    @callback
    def unloaded():
        if not closed:
            try:
                connection.send_event(msg["id"], {"type": "unloaded"})
            finally:
                cancel()
    connection.subscriptions[msg["id"]] = cancel
    runtime.entry.async_on_unload(unloaded)
    connection.send_result(msg["id"])
    await publish()


@callback
def async_register(hass):
    if hass.data.get("charge_tally_api_registered"):
        return
    for command, schema in SCHEMAS.items():
        async def handler(hass, connection, msg, command=command):
            try:
                if command == "subscribe":
                    await subscribe(hass, connection, msg)
                else:
                    result = await execute(hass, connection.user, command, {k: v for k, v in msg.items() if k not in ("id", "type")})
                    connection.send_result(msg["id"], result)
            except ValueError as err:
                connection.send_error(msg["id"], error_code(err), "The request could not be applied")
        wrapped = websocket_api.websocket_command({vol.Required("type"): DOMAIN + "/" + command, **schema})(websocket_api.async_response(handler))
        websocket_api.async_register_command(hass, wrapped)
    for command in ("start", "end", "reassign"):
        schema = {**WRITE, vol.Optional("point_id"): ID, vol.Optional("record_id"): ID,
                  vol.Optional("entity_id"): vol.Any(ID, vol.All([ID], vol.Length(min=1, max=1)))}
        if command in ("start", "reassign"):
            schema[vol.Required("identity_id") if command == "reassign" else vol.Optional("identity_id")] = ID
        if command in ("end", "reassign"):
            schema[vol.Required("expected_revision")] = REV
        async def service(call, command=command):
            user = await hass.auth.async_get_user(call.context.user_id) if call.context.user_id else None
            if call.context.user_id and (user is None or not user.is_active):
                raise Unauthorized()
            data = dict(call.data)
            runtime = current_runtime(hass)
            entity_id = data.pop("entity_id", None)
            if entity_id is not None:
                entity_id = entity_id[0] if isinstance(entity_id, list) else entity_id
                points = [p for p in runtime.points if anchor_for(runtime, p) == entity_id]
                if len(points) != 1 or data.get("point_id", points[0]) != points[0]:
                    raise Unauthorized()
                data["point_id"] = points[0]
            if command == "start" and data.get("record_id"):
                raise ServiceValidationError("Start requires a point target")
            if command in ("end", "reassign") and not data.get("record_id"):
                point_id = data.get("point_id")
                authorize(runtime, user, point_id, POLICY_CONTROL)
                key = sha256(((user.id if user else "system") + ":" + data["request_id"]).encode()).hexdigest()
                previous = await runtime.async_api_metadata("request", key)
                if previous and previous["command"] == command and previous["payload"].get("point_id") == point_id:
                    data["record_id"] = previous["payload"]["record_id"]
                else:
                    point = next((p for p in runtime.snapshot["points"] if p["id"] == point_id), None)
                    if not point or not point["active_record"]:
                        raise ServiceValidationError("No active record for target")
                    data["record_id"] = point["active_record"]["id"]
            try:
                return await execute(hass, user, command, data)
            except (ValueError, vol.Invalid) as err:
                raise ServiceValidationError("The request could not be applied", translation_domain=DOMAIN,
                    translation_key=error_code(err)) from None
        hass.services.async_register(DOMAIN, command, service, schema=vol.Schema(schema), supports_response=SupportsResponse.OPTIONAL)
    hass.data["charge_tally_api_registered"] = True
