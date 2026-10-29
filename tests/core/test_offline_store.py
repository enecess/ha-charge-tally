"""Outage boundaries preserve physical totals without reopening finalized bills."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.charge_tally.runtime_store import RuntimeStore

T = datetime(2026, 1, 1, 10, tzinfo=UTC)
POINT = {
    "name": "Point",
    "input_mode": "energy_power",
    "energy_entity": "sensor.energy",
    "power_entity": "sensor.power",
    "price": {"mode": "static", "value": "0.5"},
    "max_gap_seconds": 600,
    "resetting": True,
    "periods": [],
    "detection": {
        "enabled": True,
        "start_w": 100,
        "end_w": 10,
        "start_seconds": 30,
        "end_seconds": 60,
    },
}


def observe(store, role, seconds, value):
    return store.apply(
        "observe",
        "p",
        role,
        {
            "at": (T + timedelta(seconds=seconds)).isoformat(),
            "value": value,
            "unit": "W" if role == "power" else "kWh",
            "state_class": "measurement" if role == "power" else "total_increasing",
        },
    )[0]


@pytest.fixture
def store(tmp_path):
    runtime = RuntimeStore(str(tmp_path / "ledger.sqlite3"), "EUR", "UTC")
    runtime.apply("configure", {"p": POINT}, {"car": {"name": "Car"}}, T, "UTC")
    observe(runtime, "energy", 0, "100")
    observe(runtime, "power", 0, "0")
    yield runtime
    runtime.ledger.close()


def start(store, source="manual"):
    record = store.accounting.start(
        "p", "car", T, "start", source=source, timezone="UTC"
    )
    if source == "automatic":
        store.states["p"]["detector"] = {
            "state": "charging",
            "candidate": None,
            "identity_id": "car",
            "last_at": T.isoformat(),
            "blocked": False,
        }
    return record


def test_short_energy_outage_recovers_the_whole_counter_delta(store):
    record = start(store)
    for seconds, value in (
        (60, "101"),
        (90, "unavailable"),
        (120, "103"),
        (180, "104"),
    ):
        observe(store, "energy", seconds, value)
    current = store.ledger.get_record(record["id"])
    assert Decimal(store.states["p"]["normalized_energy_kwh"]) == 4
    assert Decimal(current["energy_kwh"]) == 4
    assert Decimal(current["known_cost"]) == 2
    assert current["cost_complete"]


@pytest.mark.parametrize("restored,ended", [(389, False), (390, True), (420, True)])
def test_recovery_boundary_is_checked_before_processing_the_new_reading(
    store, restored, ended
):
    record = start(store)
    observe(store, "energy", 60, "101")
    observe(store, "energy", 90, "unavailable")
    observe(store, "energy", restored, "103")
    current = store.ledger.get_record(record["id"])
    assert (current["status"] == "ended") is ended
    if ended:
        assert current["end"] == (T + timedelta(seconds=90)).isoformat()
        assert current["end_reason"] == "source_unavailable"
        assert Decimal(current["known_cost"]) == Decimal("0.5")
    else:
        assert Decimal(current["known_cost"]) == Decimal("1.5")


def test_timeout_ends_at_outage_start_and_never_bills_recovered_delta(store):
    record = start(store)
    observe(store, "energy", 60, "101")
    observe(store, "energy", 90, "unavailable")
    observe(store, "energy", 200, "unavailable")
    store.apply("expire_unavailable", "p", T + timedelta(seconds=390))
    ended = store.ledger.get_record(record["id"])
    assert ended["end"] == (T + timedelta(seconds=90)).isoformat()
    assert "pending_settlement" not in ended["quality"]
    observe(store, "energy", 500, "110")
    assert store.ledger.get_record(record["id"]) == ended
    assert Decimal(store.states["p"]["normalized_energy_kwh"]) == 10
    second, _ = store.apply(
        "command",
        "start",
        {"point_id": "p", "identity_id": "car", "request_id": "second"},
        T + timedelta(seconds=500),
    )
    observe(store, "energy", 560, "111")
    assert Decimal(store.ledger.get_record(second["id"])["energy_kwh"]) == 1
    assert Decimal(store.ledger.get_record(second["id"])["known_cost"]) == Decimal(
        "0.5"
    )
    assert store.ledger.get_record(record["id"]) == ended


def test_all_required_sources_must_recover_before_deadline_is_cleared(store):
    record = start(store, "automatic")
    observe(store, "energy", 60, "101")
    observe(store, "power", 90, "unavailable")
    observe(store, "energy", 100, "unavailable")
    observe(store, "power", 110, "1000")
    assert (
        store.snapshot()["points"][0]["unavailable_since"]
        == (T + timedelta(seconds=90)).isoformat()
    )
    observe(store, "energy", 390, "102")
    assert (
        store.ledger.get_record(record["id"])["end"]
        == (T + timedelta(seconds=90)).isoformat()
    )


def test_power_outage_retracts_provisional_energy_after_backdated_end(store):
    record = start(store, "automatic")
    observe(store, "energy", 60, "101")
    observe(store, "power", 90, "unavailable")
    observe(store, "energy", 120, "102")
    observe(store, "energy", 360, "106")
    assert Decimal(store.ledger.get_record(record["id"])["energy_kwh"]) == 6
    store.apply("expire_unavailable", "p", T + timedelta(seconds=390))
    ended = store.ledger.get_record(record["id"])
    assert Decimal(ended["energy_kwh"]) == Decimal("1.5")
    assert Decimal(ended["known_cost"]) == Decimal("0.75")
    observe(store, "energy", 420, "107")
    assert store.ledger.get_record(record["id"]) == ended


def test_manual_energy_power_record_does_not_end_for_display_power_loss(store):
    record = start(store)
    observe(store, "power", 90, "unavailable")
    observe(store, "energy", 420, "104")
    store.apply("maintenance", T + timedelta(seconds=600))
    assert store.active("p")["id"] == record["id"]
    assert Decimal(store.active("p")["known_cost"]) == 2


def test_silent_long_interval_is_allocated_without_offline_timeout(store):
    record = start(store)
    observe(store, "energy", 1200, "104")
    assert store.active("p")["id"] == record["id"]
    assert Decimal(store.active("p")["known_cost"]) == 2
    assert "estimated" in store.active("p")["quality"]


def test_restart_does_not_extend_persisted_outage_deadline(store):
    record = start(store)
    observe(store, "energy", 60, "101")
    observe(store, "energy", 90, "unavailable")
    checkpoint = store.ledger.get_checkpoint("runtime")
    assert checkpoint["p"]["outage"]["since"] == (T + timedelta(seconds=90)).isoformat()
    store.states["p"]["available"] = False
    store.apply(
        "configure",
        {"p": POINT},
        {"car": {"name": "Car"}},
        T + timedelta(seconds=480),
        "UTC",
    )
    assert (
        store.ledger.get_record(record["id"])["end"]
        == (T + timedelta(seconds=90)).isoformat()
    )


def test_timeout_rearm_waits_for_fresh_energy_then_allows_high_power(store):
    record = start(store, "automatic")
    observe(store, "energy", 60, "101")
    observe(store, "power", 90, "unavailable")
    observe(store, "energy", 120, "102")
    store.apply("expire_unavailable", "p", T + timedelta(seconds=390))
    observe(store, "power", 400, "1000")
    with pytest.raises(ValueError, match="baseline"):
        store.apply(
            "command",
            "start",
            {"point_id": "p", "request_id": "early"},
            T + timedelta(seconds=400),
        )
    observe(store, "energy", 405, "110")
    observe(store, "power", 435, "1000")
    assert store.active("p")["id"] != record["id"]
    assert store.active("p")["start"] == (T + timedelta(seconds=405)).isoformat()
    observe(store, "energy", 465, "111")
    assert Decimal(store.active("p")["energy_kwh"]) == 1


def test_power_only_gap_is_not_recovered_from_integral_counter(store):
    point = {**POINT, "input_mode": "power"}
    store.apply("configure", {"p": point}, {"car": {"name": "Car"}}, T, "UTC")
    observe(store, "energy", 0, "100")
    record = start(store)
    observe(store, "energy", 60, "101")
    observe(store, "power", 90, "unavailable")
    observe(store, "power", 100, "1000")
    observe(store, "energy", 120, "103")
    current = store.ledger.get_record(record["id"])
    assert Decimal(current["energy_kwh"]) == 1
    assert not current["cost_complete"]
    assert "missing_energy" in current["quality"]


def test_integral_history_cannot_fill_a_known_raw_power_outage(store):
    point = {**POINT, "input_mode": "power"}
    store.apply("configure", {"p": point}, {"car": {"name": "Car"}}, T, "UTC")
    observe(store, "energy", 0, "100")
    record = start(store)
    observe(store, "energy", 60, "101")
    observe(store, "power", 90, "unavailable")
    observe(store, "power", 100, "1000")
    observe(store, "energy", 120, "103")
    before = store.ledger.get_record(record["id"])
    store.apply(
        "import_history",
        "p",
        [
            {
                "start": (T + timedelta(seconds=left)).isoformat(),
                "end": (T + timedelta(seconds=right)).isoformat(),
                "energy_kwh": "1",
                "quality": [],
                "gap": False,
            }
            for left, right in [(60, 90), (90, 120)]
        ],
    )
    assert store.ledger.get_record(record["id"]) == before


@pytest.mark.parametrize("first_role", ["energy", "power"])
def test_restart_does_not_clear_outage_using_cached_other_source(
    store, tmp_path, first_role
):
    record = start(store, "automatic")
    observe(store, first_role, 90, "unavailable")
    restored = RuntimeStore(str(tmp_path / "ledger.sqlite3"), "EUR", "UTC")
    try:
        restored.apply(
            "configure",
            {"p": POINT},
            {"car": {"name": "Car"}},
            T + timedelta(seconds=200),
            "UTC",
        )
        observe(restored, first_role, 200, "102" if first_role == "energy" else "1000")
        observe(
            restored,
            "power" if first_role == "energy" else "energy",
            200,
            "unavailable",
        )
        assert (
            restored.states["p"]["outage"]["since"]
            == (T + timedelta(seconds=90)).isoformat()
        )
        restored.apply("expire_unavailable", "p", T + timedelta(seconds=390))
        ended = restored.ledger.get_record(record["id"])
        assert ended["status"] == "ended"
        assert ended["end"] == (T + timedelta(seconds=90)).isoformat()
    finally:
        restored.ledger.close()


@pytest.mark.parametrize("price,known", [(None, False), (Decimal(0), True)])
def test_legacy_zero_subtotal_projection_uses_actual_priced_segments(
    store, price, known
):
    record = start(store)
    store.accounting.add_interval(
        "p", T, T + timedelta(seconds=60), Decimal(1), [(T, price)]
    )
    legacy = store.ledger.get_record(record["id"])
    legacy.pop("has_known_cost")
    store.ledger.save_record(
        legacy, store.ledger.list_segments(record["id"]), audit=False
    )
    snapshot = store.snapshot()
    assert snapshot["points"][0]["active_record"]["has_known_cost"] is known
    assert snapshot["records"][0]["has_known_cost"] is known
    assert store.query("records", {}, ["p"])["records"][0]["has_known_cost"] is known
    assert (
        store.query("record", {"record_id": record["id"]}, ["p"])["record"][
            "has_known_cost"
        ]
        is known
    )
    assert "has_known_cost" not in store.ledger.get_record(record["id"])
