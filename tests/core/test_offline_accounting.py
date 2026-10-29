"""Recovered meter deltas and finalized outage bills use real ledger evidence."""

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from custom_components.charge_tally.accounting import Accounting
from custom_components.charge_tally.ledger import Ledger

T = datetime(2026, 1, 1, 22, 50, tzinfo=UTC)
D = Decimal


class OfflineAccountingTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = Ledger(str(Path(self.directory.name) / "ledger.sqlite3"))
        self.addCleanup(self.ledger.close)
        self.ledger.put_point({"id": "p", "name": "Point", "input_mode": "energy_power"})
        self.ledger.put_identity({"id": "car", "name": "Car"})
        self.app = Accounting(self.ledger)
        self.record = self.app.start("p", "car", T, "start", timezone="UTC")

    def add(self, left, right, energy, quality=(), prices=None):
        self.app.add_interval(
            "p", T + timedelta(seconds=left), T + timedelta(seconds=right),
            D(energy), prices or [(T, D("0.5"))], quality,
        )
        return self.ledger.get_record(self.record["id"])

    def test_short_outage_allocates_meter_delta_and_cost(self):
        record = self.add(0, 120, "2", ["unavailable"])
        self.assertEqual(D(record["energy_kwh"]), 2)
        self.assertEqual(D(record["known_cost"]), 1)
        self.assertTrue(record["cost_complete"])
        self.assertTrue(record["has_known_cost"])
        self.assertIn("estimated", record["quality"])
        self.assertNotIn("missing_energy", record["quality"])
        observation = self.ledger.list_intervals("p")[0]
        self.assertTrue(observation["gap"])
        self.assertEqual(observation["allocation_basis"], "estimated")

    def test_long_interval_splits_recovered_energy_across_tariffs(self):
        record = self.add(0, 1200, "2", prices=[(T, D("0.5")), (T + timedelta(minutes=10), D("1"))])
        self.assertEqual(D(record["energy_kwh"]), 2)
        self.assertEqual(D(record["known_cost"]), D("1.5"))
        self.assertEqual([D(part["energy_kwh"]) for part in self.ledger.list_segments(record["id"])], [D(1), D(1)])
        self.assertTrue(record["cost_complete"])
        self.assertIn("estimated", record["quality"])

    def test_zero_recovered_delta_has_known_zero_fee(self):
        record = self.add(0, 120, "0", ["unavailable"])
        self.assertEqual(D(record["known_cost"]), 0)
        self.assertTrue(record["has_known_cost"])
        self.assertTrue(record["cost_complete"])

    def test_reset_and_power_only_outage_remain_missing(self):
        for mode, quality in (("energy_power", ["reset"]), ("power", ["unavailable"])):
            with self.subTest(mode=mode):
                self.ledger.put_point({"id": mode, "name": mode, "input_mode": mode})
                record = self.app.start(mode, "car", T, mode, timezone="UTC")
                self.app.add_interval(mode, T, T + timedelta(seconds=120), D(2), [(T, D("0.5"))], quality)
                result = self.ledger.get_record(record["id"])
                self.assertEqual(D(result["energy_kwh"]), 0)
                self.assertFalse(result["cost_complete"])
                self.assertIn("missing_energy", result["quality"])

    def test_legacy_gap_keeps_its_original_missing_semantics(self):
        observation = self.app._interval_data("p", T, T + timedelta(seconds=120), D(2), [(T, D("0.5"))], ["unavailable"])
        observation.pop("allocation_basis", None)
        self.ledger.put_interval(observation)
        record = self.app.end(self.record["id"], T + timedelta(seconds=120), "end")
        self.assertEqual(D(record["energy_kwh"]), 0)
        self.assertFalse(record["cost_complete"])

    def test_timeout_backdates_and_freezes_bill_against_history_refinement(self):
        self.add(0, 60, "1")
        provisional = self.add(60, 360, "5", ["unavailable"])
        self.assertEqual(D(provisional["energy_kwh"]), 6)
        ended = self.app.end(self.record["id"], T + timedelta(seconds=90), "timeout", reason="source_unavailable")
        self.assertEqual(ended["end"], (T + timedelta(seconds=90)).isoformat())
        self.assertEqual(D(ended["energy_kwh"]), D("1.5"))
        self.assertEqual(D(ended["known_cost"]), D("0.75"))
        revisions = self.ledger.list_revisions(ended["id"])
        self.app.replace_gap("p", T + timedelta(seconds=60), T + timedelta(seconds=360), [
            {"start": T + timedelta(seconds=60), "end": T + timedelta(seconds=90), "energy_kwh": "1", "prices": [(T, D("0.5"))]},
            {"start": T + timedelta(seconds=90), "end": T + timedelta(seconds=360), "energy_kwh": "4", "prices": [(T, D("0.5"))]},
        ])
        self.app._refresh_record(self.ledger.get_record(ended["id"]))
        self.assertEqual(self.ledger.get_record(ended["id"]), ended)
        self.assertEqual(self.ledger.list_revisions(ended["id"]), revisions)

    def test_timeout_missing_tail_is_not_pending_automatic_settlement(self):
        self.add(0, 60, "1")
        ended = self.app.end(self.record["id"], T + timedelta(seconds=90), "timeout", reason="source_unavailable")
        self.assertIn("missing_energy", ended["quality"])
        self.assertNotIn("pending_settlement", ended["quality"])
        self.assertNotIn("pending_settlement", ended["quality_spans"][0]["quality"])
        self.assertEqual(D(ended["known_cost"]), D("0.5"))
        self.add(60, 120, "1", ["unavailable"])
        self.assertEqual(self.ledger.get_record(ended["id"]), ended)

    def test_same_endpoint_refinement_is_noop_even_if_price_improves(self):
        before = self.add(0, 120, "2", ["unavailable"], prices=[(T, None)])
        observations = self.ledger.list_intervals("p")
        self.app.replace_gap("p", T, T + timedelta(seconds=120), [
            {"start": T, "end": T + timedelta(seconds=120), "energy_kwh": "2", "prices": [(T, D("0.5"))]},
        ])
        self.assertEqual(self.ledger.list_intervals("p"), observations)
        self.assertEqual(self.ledger.get_record(before["id"]), before)

    def test_known_zero_and_no_priced_segment_are_distinct(self):
        record = self.add(0, 60, "1", prices=[(T, None)])
        self.assertFalse(record["has_known_cost"])
        record = self.add(60, 120, "1", prices=[(T, D(0))])
        self.assertTrue(record["has_known_cost"])
        self.assertEqual(D(record["known_cost"]), 0)
        self.assertFalse(record["cost_complete"])
