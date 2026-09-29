"""Identity meter cycle statistics in the real Home Assistant recorder."""

from datetime import timedelta

import pytest
from test_runtime import ENERGY, setup_runtime, tick


@pytest.fixture
def mock_recorder_before_hass(recorder_db_url):
    """Prepare the recorder database before the Home Assistant fixture."""


@pytest.mark.freeze_time("2026-09-28T15:50:00+00:00")
async def test_recorder_sum_preserves_energy_and_negative_cost_across_midnight(
    recorder_mock, hass, tmp_path, freezer
):
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
        do_adhoc_statistics,
        statistics_during_period,
    )

    entry, runtime = await setup_runtime(
        hass, tmp_path, price={"mode": "static", "value": "-2"}
    )
    start = dt_util.utcnow()
    record = await runtime.async_command(
        "start", {"point_id": "point", "identity_id": "car", "request_id": "statistics"}
    )
    await async_wait_recording_done(hass)
    await tick(hass, freezer, 60)
    hass.states.async_set("sensor.energy", "110", ENERGY)
    await hass.async_block_till_done()
    latest = (await runtime.async_snapshot())["records"][0]
    await runtime.async_command(
        "end",
        {
            "record_id": record["id"],
            "expected_revision": latest["revision"],
            "request_id": "statistics-end",
        },
    )
    await async_wait_recording_done(hass)
    await tick(hass, freezer, 241)
    do_adhoc_statistics(hass, start=start)
    await async_wait_recording_done(hass)
    await tick(hass, freezer, 300)
    assert hass.states.get("sensor.car_daily_energy").state == "0"
    await async_wait_recording_done(hass)
    await tick(hass, freezer, 300)
    do_adhoc_statistics(hass, start=start + timedelta(minutes=10))
    await async_wait_recording_done(hass)
    statistics = await hass.async_add_executor_job(
        lambda: statistics_during_period(
            hass,
            start,
            statistic_ids={"sensor.car_daily_energy", "sensor.car_daily_cost"},
            period="5minute",
        )
    )
    assert statistics["sensor.car_daily_energy"][-1]["sum"] == 10
    assert statistics["sensor.car_daily_cost"][-1]["sum"] == -20
    assert await hass.config_entries.async_unload(entry.entry_id)
