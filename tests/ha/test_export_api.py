"""Authenticated PDF export scopes reads and owns real worker lifetimes."""

import asyncio
import json
import re
import threading
from decimal import Decimal
from io import BytesIO

import pytest
from aiohttp.test_utils import make_mocked_request
from homeassistant.auth.permissions import PolicyPermissions
from pypdf import PdfReader
from test_api import second_point
from test_runtime import ENERGY, setup_runtime

URL = "/api/charge_tally/export.pdf"
SCOPE = {"calendar_period": "total", "language": "en"}


async def add_record(runtime, point="point", *, hour=0, note="", cost="2"):
    preview = await runtime.async_command(
        "preview",
        {
            "point_id": point,
            "identity_id": "car",
            "start": f"2025-01-01T{hour:02d}:00:00Z",
            "end": f"2025-01-01T{hour + 1:02d}:00:00Z",
            "energy_kwh": "1",
            "cost": cost,
            "note": note,
        },
    )
    return await runtime.async_command(
        "commit_preview",
        {"token": preview["token"], "request_id": f"{point}-{hour}"},
    )


async def permit(user, runtime, points=("point",)):
    anchors = {
        p["identity_entity_id"]: True
        for p in (await runtime.async_snapshot())["points"]
        if p["id"] in points
    }
    user.permissions = PolicyPermissions({"entities": {"entity_ids": anchors}}, None)


async def assert_error(response, status, code, details=None):
    assert response.status == status
    assert response.headers["Cache-Control"] == "no-store"
    body = await response.json()
    assert body == {
        "error": {"code": code, **({"details": details} if details else {})}
    }


class RenderGate:
    """Pause a real HA executor worker without occupying the event loop."""

    def __init__(self, hass, *, error=None):
        self.hass = hass
        self.entered = asyncio.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.thread = None
        self.report = None
        self.error = error

    def __call__(self, report, language):
        self.thread = threading.get_ident()
        self.report = report
        self.hass.loop.call_soon_threadsafe(self.entered.set)
        try:
            assert self.release.wait(10), "Test failed to release the renderer"
            if self.error:
                raise self.error
            return b"%PDF-test"
        finally:
            self.finished.set()


async def test_export_returns_authorized_pdf_attachment(
    hass, tmp_path, hass_client, hass_read_only_access_token, hass_read_only_user
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await second_point(hass, entry, runtime)
    for hour in range(3):
        await add_record(runtime, hour=hour, note=f"Visible row {hour}")
    await add_record(runtime, "other", note="Private foreign row")
    await permit(hass_read_only_user, runtime)
    client = await hass_client(hass_read_only_access_token)
    response = await client.post(URL, json=SCOPE)
    assert response.status == 200
    assert response.content_type == "application/pdf"
    assert response.headers["Cache-Control"] == "no-store"
    assert re.fullmatch(
        r'attachment; filename="charge-tally-\d{8}T\d{6}Z.pdf"',
        response.headers["Content-Disposition"],
    )
    text = " ".join(
        page.extract_text() for page in PdfReader(BytesIO(await response.read())).pages
    )
    for hour in range(3):
        assert f"Visible row {hour}" in text
    assert "Private foreign" not in text
    assert "Other garage" not in text
    await hass.config_entries.async_unload(entry.entry_id)


async def test_export_rejects_anonymous(hass, tmp_path, hass_client_no_auth):
    entry, _ = await setup_runtime(hass, tmp_path)
    client = await hass_client_no_auth()
    assert (await client.post(URL, json=SCOPE)).status == 401
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"start": "2025-01-01T00:00:00Z"},
        {
            "calendar_period": "total",
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-01-02T00:00:00Z",
        },
        {"start": "2025-01-02T00:00:00Z", "end": "2025-01-01T00:00:00Z"},
        {"start": "2025-01-01", "end": "2025-01-02"},
        {"calendar_period": "weekly"},
        {"calendar_period": "total", "language": []},
        {"calendar_period": "total", "max_records": 99999},
        [],
        None,
    ],
)
async def test_export_rejects_invalid_scope(hass, tmp_path, hass_client, payload):
    entry, _ = await setup_runtime(hass, tmp_path)
    client = await hass_client()
    await assert_error(await client.post(URL, json=payload), 400, "invalid_request")
    await assert_error(await client.post(URL, data="not JSON"), 400, "invalid_request")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_export_oversized_request_is_controlled_and_next_export_recovers(
    hass, tmp_path, hass_client
):
    entry, _ = await setup_runtime(hass, tmp_path)
    try:
        client = await hass_client()
        await assert_error(
            await client.post(
                URL,
                data=json.dumps(
                    {**SCOPE, "language": "x" * (hass.http.app._client_max_size + 1)}
                ),
                headers={"Content-Type": "application/json"},
            ),
            413,
            "export_too_large",
        )
        await assert_error(
            await client.post(URL, data="not JSON"), 400, "invalid_request"
        )
        await assert_error(await client.post(URL, json={}), 400, "invalid_request")
        response = await client.post(URL, json=SCOPE)
        assert response.status == 200
        assert (await response.read()).startswith(b"%PDF-")
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_export_compact_numeric_work_is_controlled_before_layout(
    hass, tmp_path, hass_client, monkeypatch
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    try:
        await add_record(runtime, cost="1e100000")
        from custom_components.charge_tally import pdf_report

        def no_layout(*args):
            raise RuntimeError("Unsafe numeric work reached layout")

        with monkeypatch.context() as context:
            context.setattr(pdf_report, "_render", no_layout)
            client = await hass_client()
            await assert_error(
                await client.post(URL, json=SCOPE), 413, "export_too_large"
            )
        report = await runtime.async_query("report", {"calendar_period": "total"})
        assert Decimal(report["rows"][0]["known_cost"]) == Decimal("1e100000")
        response = await client.post(
            URL,
            json={"start": "2020-01-01T00:00:00Z", "end": "2020-01-02T00:00:00Z"},
        )
        assert response.status == 200
        assert (await response.read()).startswith(b"%PDF-")
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_export_forbidden_point_and_empty_scope_hide_names(
    hass,
    tmp_path,
    hass_client,
    hass_read_only_access_token,
    hass_read_only_user,
    monkeypatch,
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await add_record(runtime, note="Private note")
    await permit(hass_read_only_user, runtime, ())
    from custom_components.charge_tally import export_api

    reports = []
    monkeypatch.setattr(
        export_api,
        "render_pdf",
        lambda report, language: reports.append(report) or b"%PDF-empty",
    )
    client = await hass_client(hass_read_only_access_token)
    await assert_error(
        await client.post(URL, json={**SCOPE, "point_id": "point"}), 403, "forbidden"
    )
    response = await client.post(URL, json={**SCOPE, "identity_id": "car"})
    assert response.status == 200
    assert reports[0]["rows"] == []
    assert reports[0]["scope"]["identity_name"] is None
    assert reports[0]["summary"]["matched_count"] == 0
    assert "Car" not in json.dumps(reports[0])
    assert "Private note" not in json.dumps(reports[0])
    await hass.config_entries.async_unload(entry.entry_id)


async def test_export_archived_point_is_admin_only(
    hass, tmp_path, hass_client, hass_read_only_access_token, hass_read_only_user
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await add_record(runtime)
    await permit(hass_read_only_user, runtime)
    hass.config_entries.async_remove_subentry(entry, "point")
    await runtime.async_refresh_config()
    user = await hass_client(hass_read_only_access_token)
    await assert_error(
        await user.post(URL, json={**SCOPE, "point_id": "point"}), 403, "forbidden"
    )
    admin = await hass_client()
    assert (await admin.post(URL, json={**SCOPE, "point_id": "point"})).status == 200
    await hass.config_entries.async_unload(entry.entry_id)


async def test_route_registration_survives_unload_reload(
    hass, tmp_path, hass_client, monkeypatch
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    from custom_components.charge_tally import export_api

    route_count = len(list(hass.http.app.router.routes()))
    export_api.async_register_export(hass)
    export_api.async_register_export(hass)
    assert len(list(hass.http.app.router.routes())) == route_count
    reports = []
    monkeypatch.setattr(
        export_api,
        "render_pdf",
        lambda report, language: reports.append(report) or b"%PDF-test",
    )
    client = await hass_client()
    assert (await client.post(URL, json=SCOPE)).status == 200
    await hass.config_entries.async_unload(entry.entry_id)
    await assert_error(await client.post(URL, json=SCOPE), 503, "export_unavailable")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data is not runtime
    assert (await client.post(URL, json=SCOPE)).status == 200
    assert len(reports) == 2
    assert len(list(hass.http.app.router.routes())) == route_count
    for path in (
        "/charge_tally/export.pdf",
        "/charge_tally/fonts/SarasaUiSC-Regular.ttf",
        "/charge_tally/ledger.sqlite3",
    ):
        assert (await client.get(path)).status == 404
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "change", ["permission", "inactive", "removed", "unload", "reload", "closing"]
)
@pytest.mark.parametrize("glyph", [False, True])
async def test_export_revalidates_before_file_or_glyph_details(
    hass,
    tmp_path,
    hass_client,
    hass_read_only_access_token,
    hass_read_only_user,
    monkeypatch,
    change,
    glyph,
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await add_record(runtime)
    await permit(hass_read_only_user, runtime)
    from custom_components.charge_tally import export_api
    from custom_components.charge_tally.pdf_report import PdfReportError

    gate = RenderGate(
        hass,
        error=PdfReportError(
            "export_missing_glyph",
            {"field": "note", "row": 1, "codepoints": ["U+1F600"]},
        )
        if glyph
        else None,
    )
    monkeypatch.setattr(export_api, "render_pdf", gate)
    client = await hass_client(hass_read_only_access_token)
    first = asyncio.create_task(client.post(URL, json=SCOPE))
    try:
        await asyncio.wait_for(gate.entered.wait(), 5)
        if change == "permission":
            await permit(hass_read_only_user, runtime, ())
        elif change == "inactive":
            hass_read_only_user.is_active = False
        elif change == "removed":
            await hass.auth.async_remove_user(hass_read_only_user)
        elif change == "closing":
            runtime._closing = True
        else:
            await hass.config_entries.async_unload(entry.entry_id)
            if change == "reload":
                assert await hass.config_entries.async_setup(entry.entry_id)
                await assert_error(
                    await client.post(URL, json=SCOPE), 429, "export_busy"
                )
        gate.release.set()
        await assert_error(
            await first,
            503 if change in {"unload", "reload", "closing"} else 403,
            "export_unavailable"
            if change in {"unload", "reload", "closing"}
            else "forbidden",
        )
    finally:
        gate.release.set()
        await first
        runtime._closing = False
        hass_read_only_user.is_active = True
    await hass.config_entries.async_unload(entry.entry_id)


async def test_export_worker_is_separate_and_single_slot_keeps_ledger_live(
    hass, tmp_path, hass_client, monkeypatch
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    from custom_components.charge_tally import export_api

    gate = RenderGate(hass)
    monkeypatch.setattr(export_api, "render_pdf", gate)
    client = await hass_client()
    first = asyncio.create_task(client.post(URL, json=SCOPE))
    try:
        await asyncio.wait_for(gate.entered.wait(), 5)
        assert gate.thread != threading.get_ident()
        assert gate.thread != await runtime._read(threading.get_ident)
        await assert_error(await client.post(URL, json=SCOPE), 429, "export_busy")
        await asyncio.wait_for(runtime.async_select_identity("point", "car"), 5)
        assert runtime.snapshot["points"][0]["selected_identity_id"] == "car"
        hass.states.async_set("sensor.energy", "101", ENERGY)
        await hass.async_block_till_done()
        assert not gate.finished.is_set()
        assert (
            Decimal(
                (await runtime.async_snapshot())["points"][0]["normalized_energy_kwh"]
            )
            == 1
        )
        assert (await runtime.async_query("report", {"calendar_period": "total"}))[
            "data_version"
        ] > gate.report["data_version"]
    finally:
        gate.release.set()
        assert (await first).status == 200
    await hass.config_entries.async_unload(entry.entry_id)


async def test_cancelling_handler_keeps_slot_until_real_worker_finishes(
    hass, tmp_path, hass_admin_user, hass_client, monkeypatch
):
    entry, _ = await setup_runtime(hass, tmp_path)
    from custom_components.charge_tally import export_api

    gate = RenderGate(hass, error=RuntimeError("Private exception after cancellation"))
    monkeypatch.setattr(export_api, "render_pdf", gate)
    request = make_mocked_request("POST", URL)
    request["hass_user"] = hass_admin_user

    async def body():
        return dict(SCOPE)

    monkeypatch.setattr(type(request), "json", lambda self: body())
    first = asyncio.create_task(export_api.ExportPdfView(hass).post(request))
    client = await hass_client()
    try:
        await asyncio.wait_for(gate.entered.wait(), 5)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not gate.finished.is_set()
        await assert_error(await client.post(URL, json=SCOPE), 429, "export_busy")
    finally:
        gate.release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert gate.finished.is_set()
    monkeypatch.setattr(export_api, "render_pdf", lambda report, language: b"%PDF-next")
    assert (await client.post(URL, json=SCOPE)).status == 200
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "kind", ["records", "segments", "bytes", "glyph", "content", "unknown", "value"]
)
async def test_export_limits_and_safe_errors(
    hass, tmp_path, hass_client, monkeypatch, kind
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await add_record(runtime)
    await add_record(runtime, hour=1)
    from custom_components.charge_tally import export_api, reports
    from custom_components.charge_tally.pdf_report import PdfReportError

    details = {"field": "note", "row": 1, "codepoints": ["U+1F600"]}
    if kind in {"records", "segments"}:
        monkeypatch.setattr(reports, "MAX_REPORT_" + kind.upper(), 1)
    elif kind == "bytes":
        monkeypatch.setattr(export_api, "MAX_PDF_BYTES", 8)
        monkeypatch.setattr(
            export_api, "render_pdf", lambda report, language: b"%PDF-1234"
        )
    else:
        error = (
            PdfReportError("export_missing_glyph", details)
            if kind == "glyph"
            else PdfReportError("export_failed")
            if kind == "content"
            else ValueError("export_too_large private data")
            if kind == "value"
            else RuntimeError("Secret user name and note")
        )

        def fail(report, language):
            raise error

        monkeypatch.setattr(export_api, "render_pdf", fail)
    client = await hass_client()
    await assert_error(
        await client.post(URL, json=SCOPE),
        413
        if kind in {"records", "segments", "bytes"}
        else 422
        if kind in {"glyph", "content"}
        else 500,
        "export_too_large"
        if kind in {"records", "segments", "bytes"}
        else "export_missing_glyph"
        if kind == "glyph"
        else "export_failed",
        details if kind == "glyph" else None,
    )
    await hass.config_entries.async_unload(entry.entry_id)


async def test_cancelled_http_client_keeps_slot_until_worker_finishes(
    hass, tmp_path, hass_client, monkeypatch
):
    entry, _ = await setup_runtime(hass, tmp_path)
    from custom_components.charge_tally import export_api

    gate = RenderGate(hass)
    monkeypatch.setattr(export_api, "render_pdf", gate)
    client = await hass_client()
    first = asyncio.create_task(client.post(URL, json=SCOPE))
    try:
        await asyncio.wait_for(gate.entered.wait(), 5)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not gate.finished.is_set()
        await assert_error(await client.post(URL, json=SCOPE), 429, "export_busy")
    finally:
        gate.release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert gate.finished.is_set()
    monkeypatch.setattr(export_api, "render_pdf", lambda report, language: b"%PDF-next")
    assert (await client.post(URL, json=SCOPE)).status == 200
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "has_rows, point_filter", [(False, False), (False, True), (True, False)]
)
async def test_empty_report_identity_name_revalidates_and_unused_point_may_be_revoked(
    hass,
    tmp_path,
    hass_client,
    hass_read_only_access_token,
    hass_read_only_user,
    monkeypatch,
    has_rows,
    point_filter,
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await second_point(hass, entry, runtime)
    if has_rows:
        await add_record(runtime)
    await permit(
        hass_read_only_user, runtime, ("point", "other") if has_rows else ("point",)
    )
    from custom_components.charge_tally import export_api

    gate = RenderGate(hass)
    monkeypatch.setattr(export_api, "render_pdf", gate)
    client = await hass_client(hass_read_only_access_token)
    filters = {"point_id": "point"} if point_filter else {"identity_id": "car"}
    first = asyncio.create_task(client.post(URL, json={**SCOPE, **filters}))
    try:
        await asyncio.wait_for(gate.entered.wait(), 5)
        if point_filter:
            assert gate.report["scope"]["point_name"] == "Garage"
        else:
            assert gate.report["scope"]["identity_name"] == "Car"
        await permit(hass_read_only_user, runtime, ("point",) if has_rows else ())
        gate.release.set()
        response = await first
        if has_rows:
            assert response.status == 200
        else:
            await assert_error(response, 403, "forbidden")
    finally:
        gate.release.set()
        await first
    await hass.config_entries.async_unload(entry.entry_id)


async def test_actual_renderer_glyph_error_and_next_export_recover(
    hass, tmp_path, hass_client
):
    entry, runtime = await setup_runtime(hass, tmp_path)
    await add_record(runtime, note="Unsupported \U0001f600")
    client = await hass_client()
    await assert_error(
        await client.post(URL, json=SCOPE),
        422,
        "export_missing_glyph",
        {"field": "note", "row": 1, "codepoints": ["U+1F600"]},
    )
    response = await client.post(
        URL, json={"start": "2020-01-01T00:00:00Z", "end": "2020-01-02T00:00:00Z"}
    )
    assert response.status == 200
    assert (await response.read()).startswith(b"%PDF-")
    await hass.config_entries.async_unload(entry.entry_id)
