"""Cold PDF startup imports must leave HA's event loop available."""

import asyncio
import os
import sys
import threading

from homeassistant.setup import async_setup_component
from test_runtime import setup_runtime


async def test_pdf_cold_import_runs_off_loop(hass, tmp_path, hass_client, monkeypatch):
    # Other test modules import the renderer during collection, so isolate the cold load.
    if os.environ.get("_CHARGE_TALLY_COLD_IMPORT_TEST") != "1":
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pytest",
            "-q",
            f"{__file__}::test_pdf_cold_import_runs_off_loop",
            env={**os.environ, "_CHARGE_TALLY_COLD_IMPORT_TEST": "1"},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 45)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert process.returncode == 0, output.decode()
        return

    assert "custom_components.charge_tally.export_api" not in sys.modules
    assert "custom_components.charge_tally.pdf_report" not in sys.modules
    assert "reportlab" not in sys.modules
    assert await async_setup_component(hass, "http", {})
    loop_thread = threading.get_ident()
    import_threads = {}
    directory_threads = []
    registration_threads = []
    original_isdir = os.path.isdir
    original_register = hass.http.register_view

    def observe_import(event, args):
        if event == "exec":
            filename = args[0].co_filename.replace("\\", "/")
            if filename.endswith(
                (
                    "/charge_tally/export_api.py",
                    "/charge_tally/pdf_report.py",
                    "/reportlab/rl_config.py",
                )
            ):
                import_threads[filename] = threading.get_ident()

    def observe_isdir(path):
        if sys._getframe(1).f_globals.get("__name__") == "reportlab.lib.utils":
            directory_threads.append(threading.get_ident())
        return original_isdir(path)

    def observe_registration(view):
        if view.url == "/api/charge_tally/export.pdf":
            registration_threads.append(threading.get_ident())
        return original_register(view)

    # Audit hooks live only in this subprocess and observe real module execution.
    sys.addaudithook(observe_import)
    monkeypatch.setattr(os.path, "isdir", observe_isdir)
    monkeypatch.setattr(hass.http, "register_view", observe_registration)
    entry, _ = await setup_runtime(hass, tmp_path)
    try:
        assert len(import_threads) == 3, import_threads
        assert loop_thread not in import_threads.values(), import_threads
        assert directory_threads, "ReportLab must perform its real startup path scan"
        assert loop_thread not in directory_threads
        assert registration_threads == [loop_thread]
        client = await hass_client()
        response = await client.post("/api/charge_tally/export.pdf", json={})
        assert response.status == 400
        assert await response.json() == {"error": {"code": "invalid_request"}}
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
