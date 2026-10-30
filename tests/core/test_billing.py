"""Consolidated billing preserves exact amounts and accounting boundaries."""

import copy
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from custom_components.charge_tally.core import billing
from custom_components.charge_tally.core.billing import billing_segments


def sample(index, **overrides):
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index * 5)
    part = dict(
        start=start.isoformat(),
        end=(start + timedelta(seconds=5)).isoformat(),
        local_date="2026-01-01",
        energy_kwh="0.001",
        cost="0.0005",
        unit_price="0.5",
        cost_basis="tariff",
        quality=[],
        observation_id=f"obs-{index}",
    )
    part.update(overrides)
    return part


class BillingTests(unittest.TestCase):
    def test_720_samples_become_one_independent_billing_segment(self):
        parts = [sample(i) for i in range(720)]
        before = copy.deepcopy(parts)
        result = billing_segments(parts)
        self.assertEqual(len(result), 1)
        self.assertEqual(Decimal(result[0]["energy_kwh"]), Decimal("0.720"))
        self.assertEqual(Decimal(result[0]["cost"]), Decimal("0.3600"))
        self.assertNotIn("observation_id", result[0])
        result[0]["quality"].append("changed")
        self.assertEqual(parts, before)

    def test_boundaries_do_not_merge(self):
        for change in (
            {"quality": ["estimated"]},
            {"unit_price": "0.6"},
            {"local_date": "2026-01-02"},
            {"cost_basis": "manual"},
            {"start": "2026-01-01T00:00:06+00:00"},
            {"cost": None},
        ):
            with self.subTest(change=change):
                self.assertEqual(
                    len(billing_segments([sample(0), sample(1, **change)])), 2
                )

    def test_equivalent_prices_quality_sets_and_actual_instants_merge(self):
        result = billing_segments(
            [
                sample(0, quality=["a", "b"]),
                sample(
                    1,
                    start="2026-01-01T08:00:05+08:00",
                    unit_price="0.5000",
                    quality=["b", "a"],
                ),
            ]
        )
        self.assertEqual(len(result), 1)

    def test_zero_energy_unknown_cost_and_negative_cost(self):
        for changes, expected in (
            ({"energy_kwh": "0", "cost": "0"}, "0"),
            ({"unit_price": None, "cost": None}, None),
            ({"unit_price": "-0.5", "cost": "-0.0005"}, "-0.0010"),
        ):
            with self.subTest(changes=changes):
                result = billing_segments([sample(0, **changes), sample(1, **changes)])
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["cost"], expected)

    def test_first_estimated_part_stays_separate(self):
        self.assertEqual(
            len(
                billing_segments(
                    [sample(0, quality=["estimated"]), sample(1), sample(2)]
                )
            ),
            2,
        )

    def test_missing_metadata_is_rejected(self):
        for field in (
            "start",
            "end",
            "local_date",
            "energy_kwh",
            "cost",
            "unit_price",
            "cost_basis",
            "quality",
        ):
            with self.subTest(field=field):
                part = sample(0)
                del part[field]
                with self.assertRaises((KeyError, ValueError)):
                    billing_segments([part])

    def test_empty_parts(self):
        self.assertEqual(billing_segments([]), [])


class BillingPeriodTests(unittest.TestCase):
    def test_quality_only_boundaries_merge_without_changing_evidence(self):
        parts = [
            sample(0, quality=["estimated"]),
            sample(1, unit_price="0.5000"),
            sample(2, quality=["unavailable", "gap"]),
        ]
        before = copy.deepcopy(parts)
        result = billing.billing_periods(parts)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["quality"], ["estimated", "gap", "unavailable"])
        self.assertEqual(Decimal(result[0]["energy_kwh"]), Decimal("0.003"))
        self.assertEqual(Decimal(result[0]["cost"]), Decimal("0.0015"))
        self.assertEqual(len(billing_segments(parts)), 3)
        result[0]["quality"].append("changed")
        self.assertEqual(parts, before)

    def test_accounting_boundaries_and_actual_missing_spans_remain_separate(self):
        for change in (
            {"unit_price": "0.6"},
            {"local_date": "2026-01-02"},
            {"cost_basis": "manual"},
            {"start": "2026-01-01T00:00:05.000001+00:00"},
            {"cost": None},
            {"unit_price": None, "cost": None},
        ):
            with self.subTest(change=change):
                self.assertEqual(
                    len(billing.billing_periods([sample(0), sample(1, **change)])), 2
                )
        span = {
            "start": "2026-01-01T08:00:04+08:00",
            "end": "2026-01-01T08:00:06+08:00",
            "quality": ["missing_energy", "reset"],
        }
        self.assertEqual(
            len(billing.billing_periods([sample(0), sample(1)], [span])), 2
        )
        self.assertEqual(
            len(
                billing.billing_periods(
                    [sample(0), sample(1)], [{**span, "quality": ["estimated"]}]
                )
            ),
            1,
        )

    def test_zero_unknown_negative_cost_and_equivalent_instants(self):
        for changes, cost in (
            ({"energy_kwh": "0", "cost": "0", "unit_price": "0"}, "0"),
            ({"unit_price": None, "cost": None}, None),
            ({"unit_price": "-0.5", "cost": "-0.0005"}, "-0.0010"),
        ):
            with self.subTest(changes=changes):
                parts = [sample(0, **changes), sample(1, **changes)]
                parts[1]["start"] = "2026-01-01T08:00:05+08:00"
                result = billing.billing_periods(parts)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["cost"], cost)

    def test_microsecond_example_keeps_three_tariff_periods_and_real_gap(self):
        bounds = [
            "16:57:02.000000",
            "16:57:02.002070",
            "16:58:00.000000",
            "17:00:00.000000",
            "17:00:00.000001",
            "18:00:00.000000",
            "18:10:00.000000",
            "19:04:11.106208",
            "19:04:16.207151",
            "19:10:00.000000",
            "19:20:00.000000",
            "19:29:15.000000",
            "19:29:15.000002",
        ]
        energies = [
            "0.000001",
            "0.100000",
            "0.219499",
            "0.000001",
            "7",
            "1",
            "6.488399",
            "0.5",
            "1",
            "1",
            "0.3671",
        ]
        parts = []
        for index, (left, right) in enumerate(zip(bounds, bounds[1:])):
            if index == 7:
                continue
            position = len(parts)
            energy = energies[position]
            price = "0.25" if index < 3 else "0.30"
            parts.append(
                sample(
                    position,
                    start=f"2026-10-29T{left}+08:00",
                    end=f"2026-10-29T{right}+08:00",
                    local_date="2026-10-29",
                    energy_kwh=energy,
                    cost=str(Decimal(energy) * Decimal(price)),
                    unit_price=price,
                    quality=["estimated"] if position % 2 == 0 else ["unavailable"],
                )
            )
        spans = [
            {
                "start": "2026-10-29T19:04:11.106208+08:00",
                "end": "2026-10-29T19:04:16.207151+08:00",
                "quality": ["missing_energy", "reset"],
            }
        ]
        before = copy.deepcopy((parts, spans))
        result = billing.billing_periods(parts, spans)
        self.assertEqual(len(result), 3)
        self.assertEqual(
            [Decimal(row["energy_kwh"]) for row in result],
            [Decimal("0.319500"), Decimal("14.488400"), Decimal("2.8671")],
        )
        self.assertEqual(
            sum(Decimal(row["energy_kwh"]) for row in result), Decimal("17.675000")
        )
        self.assertEqual(
            sum(Decimal(row["cost"]) for row in result), Decimal("5.28652500")
        )
        self.assertEqual(result[1]["end"], spans[0]["start"])
        self.assertEqual(result[2]["start"], spans[0]["end"])
        self.assertEqual((parts, spans), before)
