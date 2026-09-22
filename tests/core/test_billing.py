"""Consolidated billing preserves exact amounts and accounting boundaries."""
import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from custom_components.charge_tally.core.billing import billing_segments


def sample(index, **overrides):
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index * 5)
    part = dict(start=start.isoformat(), end=(start + timedelta(seconds=5)).isoformat(),
                local_date="2026-01-01", energy_kwh="0.001", cost="0.0005",
                unit_price="0.5", cost_basis="tariff", quality=[], observation_id=f"obs-{index}")
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
        for change in ({"quality": ["estimated"]}, {"unit_price": "0.6"},
                       {"local_date": "2026-01-02"}, {"cost_basis": "manual"},
                       {"start": "2026-01-01T00:00:06+00:00"}, {"cost": None}):
            with self.subTest(change=change):
                self.assertEqual(len(billing_segments([sample(0), sample(1, **change)])), 2)

    def test_equivalent_prices_quality_sets_and_actual_instants_merge(self):
        result = billing_segments([sample(0, quality=["a", "b"]), sample(1,
            start="2026-01-01T08:00:05+08:00", unit_price="0.5000", quality=["b", "a"])])
        self.assertEqual(len(result), 1)

    def test_zero_energy_unknown_cost_and_negative_cost(self):
        for changes, expected in (({"energy_kwh": "0", "cost": "0"}, "0"),
                                  ({"unit_price": None, "cost": None}, None),
                                  ({"unit_price": "-0.5", "cost": "-0.0005"}, "-0.0010")):
            with self.subTest(changes=changes):
                result = billing_segments([sample(0, **changes), sample(1, **changes)])
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["cost"], expected)

    def test_first_estimated_part_stays_separate(self):
        self.assertEqual(len(billing_segments([sample(0, quality=["estimated"]), sample(1), sample(2)])), 2)

    def test_missing_metadata_is_rejected(self):
        for field in ("start", "end", "local_date", "energy_kwh", "cost", "unit_price", "cost_basis", "quality"):
            with self.subTest(field=field):
                part = sample(0)
                del part[field]
                with self.assertRaises((KeyError, ValueError)):
                    billing_segments([part])

    def test_empty_parts(self):
        self.assertEqual(billing_segments([]), [])
