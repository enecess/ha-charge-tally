"""Authenticated, memory-only downloads of frozen ledger report snapshots."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import voluptuous as vol
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError, Unauthorized

from .api import SCHEMAS, allowed_points, current_runtime, scoped_read
from .pdf_report import PdfReportError, render_pdf

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .runtime import Runtime

MAX_PDF_BYTES = 20 * 1024 * 1024
_REGISTERED = "charge_tally_export_registered"
_TASK = "charge_tally_export_task"
_HEADERS = {"Cache-Control": "no-store"}
_SCHEMA = vol.Schema(
    {
        **SCHEMAS["query"],
        vol.Optional("language", default="en"): vol.All(str, vol.Length(max=64)),
    }
)


def _error(code: str, status: int, details: dict | None = None) -> web.Response:
    error = {"code": code}
    if details is not None:
        error["details"] = details
    return web.json_response({"error": error}, status=status, headers=_HEADERS)


def _runtime(hass: HomeAssistant, expected: Runtime | None = None) -> Runtime:
    runtime = current_runtime(hass)
    if (
        runtime._closing
        or runtime._closed
        or (expected is not None and runtime is not expected)
    ):
        raise ServiceValidationError("Export runtime unavailable")
    return runtime


async def _revalidate(hass, runtime, user_id, report, read_ids):
    user = await hass.auth.async_get_user(user_id)
    _runtime(hass, runtime)
    if user is None or not user.is_active:
        raise Unauthorized()
    allowed = set(await allowed_points(runtime, user))
    required = {row["record"]["point_id"] for row in report["rows"]}
    if point_id := report["scope"].get("point_id"):
        required.add(point_id)
    if not required.issubset(allowed):
        raise Unauthorized()
    # An empty report can still disclose a globally visible identity filter name.
    if report["scope"].get("identity_name") is not None and not allowed.intersection(
        read_ids
    ):
        raise Unauthorized()


async def _generate(hass, runtime, user, data, language):
    read_ids = []

    async def read(ids):
        nonlocal read_ids
        _runtime(hass, runtime)
        report = await runtime.async_query("report", data, point_ids=ids)
        read_ids = ids
        return report

    report = await scoped_read(runtime, user, data.get("point_id"), read)
    await _revalidate(hass, runtime, user.id, report, read_ids)
    try:
        pdf = await hass.async_add_executor_job(render_pdf, report, language)
        if len(pdf) > MAX_PDF_BYTES:
            raise PdfReportError("export_too_large")
    except Exception as err:
        return report, read_ids, None, err
    return report, read_ids, pdf, None


class ExportPdfView(HomeAssistantView):
    """Generate an attachment for the current authenticated reader."""

    url = "/api/charge_tally/export.pdf"
    name = "api:charge_tally:export_pdf"
    requires_auth = True

    def __init__(self, hass: HomeAssistant):
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """Freeze an authorized snapshot, render off-loop, then recheck access."""
        try:
            data = _SCHEMA(await request.json())
            if "calendar_period" in data:
                if "start" in data or "end" in data:
                    raise vol.Invalid("Mixed ranges")
            elif "start" not in data or "end" not in data:
                raise vol.Invalid("A complete range is required")
            elif datetime.fromisoformat(data["start"]) >= datetime.fromisoformat(
                data["end"]
            ):
                raise vol.Invalid("Invalid range")
        except (ValueError, TypeError, vol.Invalid, web.HTTPBadRequest):
            return _error("invalid_request", 400)

        hass = self.hass
        try:
            runtime = _runtime(hass)
            request_user = request.get("hass_user")
            user = (
                await hass.auth.async_get_user(request_user.id)
                if request_user is not None
                else None
            )
            if user is None or not user.is_active:
                raise Unauthorized()
            _runtime(hass, runtime)
            if (pending := hass.data.get(_TASK)) is not None and not pending.done():
                return _error("export_busy", 429)
            language = data.pop("language")
            # The HA-owned task outlives a cancelled HTTP handler and owns the slot.
            task = hass.async_create_background_task(
                _generate(hass, runtime, user, data, language),
                "charge_tally_pdf_export",
            )
            hass.data[_TASK] = task

            @callback
            def finished(done):
                if hass.data.get(_TASK) is done:
                    hass.data.pop(_TASK)
                if not done.cancelled():
                    done.exception()

            task.add_done_callback(finished)
            report, read_ids, pdf, error = await asyncio.shield(task)
            await _revalidate(hass, runtime, user.id, report, read_ids)
            if error is not None:
                if isinstance(error, PdfReportError):
                    if error.code == "export_missing_glyph":
                        return _error(error.code, 422, error.details)
                    if error.code == "export_too_large":
                        return _error(error.code, 413)
                    if error.code == "export_failed":
                        return _error(error.code, 422)
                return _error("export_failed", 500)
        except Unauthorized:
            return _error("forbidden", 403)
        except ServiceValidationError:
            return _error("export_unavailable", 503)
        except ValueError as err:
            if str(err) == "export_too_large":
                return _error("export_too_large", 413)
            try:
                _runtime(hass, runtime)
            except ServiceValidationError:
                return _error("export_unavailable", 503)
            return _error("export_failed", 500)
        except Exception:
            return _error("export_failed", 500)
        filename = datetime.now(UTC).strftime("charge-tally-%Y%m%dT%H%M%SZ.pdf")
        return web.Response(
            body=pdf,
            content_type="application/pdf",
            headers={
                **_HEADERS,
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )


@callback
def async_register_export(hass: HomeAssistant) -> None:
    """Register once after HTTP setup; each request resolves its current runtime."""
    if hass.http is not None and not hass.data.get(_REGISTERED):
        hass.http.register_view(ExportPdfView(hass))
        hass.data[_REGISTERED] = True
