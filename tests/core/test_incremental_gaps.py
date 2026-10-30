"""Historical missing evidence does not prevent safe contiguous appends."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.charge_tally.accounting import Accounting
from custom_components.charge_tally.ledger import Ledger

T = datetime(2026, 1, 1, 23, 59, 30, tzinfo=UTC)
D = Decimal


@pytest.fixture
def accounting(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.sqlite3"))
    ledger.put_identity({"id": "car", "name": "Car"})
    yield ledger, Accounting(ledger)
    ledger.close()


@pytest.mark.parametrize(
    ("input_mode", "gap_mark"),
    [("energy_power", "reset"), ("power", "unavailable")],
)
def test_contiguous_appends_preserve_historical_gaps_and_raw_segments(
    accounting, input_mode, gap_mark
):
    ledger, app = accounting
    ledger.put_point({"id": "p", "name": "Point", "input_mode": input_mode})
    record = app.start("p", "car", T, "start", timezone="UTC")
    app.add_interval(
        "p",
        T,
        T + timedelta(seconds=10),
        D(".1"),
        [(T, None), (T + timedelta(seconds=5), D(".5"))],
    )
    app.add_interval(
        "p",
        T + timedelta(seconds=10),
        T + timedelta(seconds=20),
        D(".2"),
        [(T, D(1))],
        [gap_mark],
    )
    spans = [
        {
            "start": (T + timedelta(seconds=10)).isoformat(),
            "end": (T + timedelta(seconds=20)).isoformat(),
            "quality": sorted([gap_mark, "missing_energy"]),
        }
    ]
    assert ledger.get_record(record["id"])["quality_spans"] == spans

    for left, energy, price, total_energy in [
        (20, ".3", D(2), ".4"),
        (30, ".4", None, ".8"),
        (40, ".5", D(0), "1.3"),
    ]:
        previous = ledger.get_record(record["id"])
        raw = ledger._db.execute(
            "SELECT rowid,position,observation_id,data FROM segments "
            "WHERE record_id=? ORDER BY position",
            (record["id"],),
        ).fetchall()
        sql = []
        ledger._db.set_trace_callback(sql.append)
        app.add_interval(
            "p",
            T + timedelta(seconds=left),
            T + timedelta(seconds=left + 10),
            D(energy),
            [(T + timedelta(seconds=left), price)],
        )
        ledger._db.set_trace_callback(None)

        assert not any("DELETE FROM segments" in statement for statement in sql)
        assert not any("SELECT data FROM segments" in statement for statement in sql)
        assert sum("INSERT INTO segments" in statement for statement in sql) == 1
        assert (
            ledger._db.execute(
                "SELECT rowid,position,observation_id,data FROM segments "
                "WHERE record_id=? AND position<? ORDER BY position",
                (record["id"], previous["_segment_count"]),
            ).fetchall()
            == raw
        )
        actual = ledger.get_record(record["id"])
        assert D(actual["energy_kwh"]) == D(total_energy)
        assert D(actual["known_cost"]) == D(".625")
        assert actual["has_known_cost"]
        assert not actual["cost_complete"]
        assert actual["quality_spans"] == spans
        assert actual["quality"] == sorted(
            ["estimated", gap_mark, "missing_energy", "missing_price", "provisional"]
        )
        assert actual["revision"] == previous["revision"] + 1
        assert actual["_segment_count"] == previous["_segment_count"] + 1
        assert (
            actual["_accounted_until"] == (T + timedelta(seconds=left + 10)).isoformat()
        )
        rebuilt, parts, _ = app._build(dict(actual))
        assert actual == rebuilt
        assert ledger.list_segments(record["id"]) == parts


def test_late_history_inside_accounted_range_rebuilds_and_clears_gap(accounting):
    ledger, app = accounting
    ledger.put_point({"id": "p", "name": "Point"})
    record = app.start("p", "car", T, "start", timezone="UTC")
    for left, energy in [(0, ".1"), (20, ".3"), (30, ".4")]:
        app.add_interval(
            "p",
            T + timedelta(seconds=left),
            T + timedelta(seconds=left + 10),
            D(energy),
            [(T, D(2))],
        )
    before = ledger.get_record(record["id"])
    assert "missing_energy" in before["quality"]
    sql = []
    ledger._db.set_trace_callback(sql.append)
    app.add_interval(
        "p", T + timedelta(seconds=10), T + timedelta(seconds=20), D(".2"), [(T, D(1))]
    )
    ledger._db.set_trace_callback(None)

    assert any("DELETE FROM segments" in statement for statement in sql)
    actual = ledger.get_record(record["id"])
    assert D(actual["energy_kwh"]) == D(1)
    assert D(actual["known_cost"]) == D("1.8")
    assert actual["cost_complete"]
    assert actual["quality"] == ["provisional"]
    assert actual["quality_spans"] == []
    assert actual["revision"] == before["revision"] + 1
    assert actual["_accounted_until"] == before["_accounted_until"]
    rebuilt, parts, _ = app._build(dict(actual))
    assert actual == rebuilt
    assert ledger.list_segments(record["id"]) == parts


def test_historical_gap_refinement_rebuilds_after_contiguous_append(accounting):
    ledger, app = accounting
    ledger.put_point({"id": "p", "name": "Point", "input_mode": "energy_power"})
    record = app.start("p", "car", T, "start", timezone="UTC")
    for left, right, energy, quality in [
        (0, 10, ".1", []),
        (10, 30, ".2", ["reset"]),
        (30, 40, ".4", []),
    ]:
        app.add_interval(
            "p",
            T + timedelta(seconds=left),
            T + timedelta(seconds=right),
            D(energy),
            [(T, D(2))],
            quality,
        )
    before = ledger.get_record(record["id"])
    assert D(before["energy_kwh"]) == D(".5")
    assert "missing_energy" in before["quality"]
    sql = []
    ledger._db.set_trace_callback(sql.append)
    app.replace_gap(
        "p",
        T + timedelta(seconds=10),
        T + timedelta(seconds=30),
        [
            {
                "start": T + timedelta(seconds=left),
                "end": T + timedelta(seconds=left + 10),
                "energy_kwh": ".1",
                "prices": [(T, price)],
            }
            for left, price in [(10, D(1)), (20, None)]
        ],
    )
    ledger._db.set_trace_callback(None)

    assert any("DELETE FROM segments" in statement for statement in sql)
    actual = ledger.get_record(record["id"])
    assert D(actual["energy_kwh"]) == D(".7")
    assert D(actual["known_cost"]) == D("1.1")
    assert actual["has_known_cost"]
    assert not actual["cost_complete"]
    assert actual["quality"] == ["missing_price", "provisional"]
    assert actual["quality_spans"] == []
    assert actual["revision"] == before["revision"] + 1
    assert actual["_accounted_until"] == before["_accounted_until"]
    rebuilt, parts, _ = app._build(dict(actual))
    assert actual == rebuilt
    assert ledger.list_segments(record["id"]) == parts
