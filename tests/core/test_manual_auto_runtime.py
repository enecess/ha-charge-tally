import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from custom_components.charge_tally.runtime_store import RuntimeStore


class ManualAutomaticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.at = datetime(2026, 1, 1, tzinfo=UTC)
        self.store = RuntimeStore(
            str(Path(self.tmp.name) / "ledger.sqlite3"), "CNY", "UTC"
        )
        self.addCleanup(lambda: self.store.ledger.close())
        self.point = {
            "name": "Point",
            "input_mode": "energy_power",
            "energy_entity": "sensor.energy",
            "power_entity": "sensor.power",
            "price": {"mode": "static", "value": "1"},
            "max_gap_seconds": 60,
            "detection": {
                "enabled": True,
                "start_w": 100,
                "end_w": 10,
                "start_seconds": 5,
                "end_seconds": 30,
            },
        }
        self.store.apply(
            "configure",
            {"p": self.point},
            {"a": {"name": "Alice"}, "b": {"name": "Bob"}},
            self.at,
            "UTC",
        )
        self.store.apply("energy", "p", self.at, Decimal(100))

    def power(self, seconds, value, **extra):
        self.store.apply(
            "observe",
            "p",
            "power",
            {
                "at": (self.at + timedelta(seconds=seconds)).isoformat(),
                "value": value,
                "unit": "W",
                **extra,
            },
        )

    def command(self, name, seconds, **payload):
        return self.store.apply(
            "command", name, payload, self.at + timedelta(seconds=seconds)
        )[0]

    def start(self, seconds=1):
        return self.command("start", seconds, point_id="p", request_id="manual")

    def end(self, record, seconds=20):
        return self.command("end", seconds, record_id=record["id"], request_id="end")

    def test_manual_low_then_end_allows_next_high_cycle(self):
        self.power(0, "0")
        record = self.start()
        self.power(10, "0")
        self.end(record)
        self.power(21, "100")
        self.power(26, "100")
        self.assertIsNotNone(self.store.active("p"))
        self.assertEqual(self.store.active("p")["source"], "automatic")

    def test_manual_start_clears_locked_candidate_and_keeps_selected_identity(self):
        self.command("select_identity", 0, point_id="p", identity_id="a")
        self.power(0, "100")
        self.command("select_identity", 1, point_id="p", identity_id="b")
        record = self.start(2)
        snapshot = self.store.snapshot()["points"][0]
        self.assertIsNone(snapshot["candidate"])
        self.assertEqual(record["identity_id"], "b")
        self.assertEqual(snapshot["recording_state"], "manual")
        self.assertEqual(snapshot["detection_state"], "paused_manual")
        self.power(10, "0")
        self.power(50, "0")
        self.assertEqual(self.store.active("p")["id"], record["id"])

    def test_snapshot_candidate_and_active_identity_remain_locked(self):
        self.command("select_identity", 0, point_id="p", identity_id="a")
        self.power(0, "100")
        self.command("select_identity", 1, point_id="p", identity_id="b")
        point = self.store.snapshot()["points"][0]
        self.assertEqual(point["candidate_identity_id"], "a")
        self.assertEqual(point["detection_state"], "pending_start")
        self.power(5, "100")
        point = self.store.snapshot()["points"][0]
        self.assertEqual(point["active_record"]["identity_id"], "a")
        self.assertIsNone(point["candidate_identity_id"])
        self.assertEqual(point["recording_state"], "automatic")

    def assert_blocked_after_end(self, record, seconds=20, source_available=True):
        self.store.apply(
            "command",
            "end",
            {"record_id": record["id"], "request_id": "end"},
            self.at + timedelta(seconds=seconds),
            source_available,
        )
        self.assertEqual(
            self.store.snapshot()["points"][0]["detection_state"], "blocked"
        )
        self.power(seconds + 1, "100")
        self.power(seconds + 6, "100")
        self.assertIsNone(self.store.active("p"))
        self.power(seconds + 7, "0")
        self.power(seconds + 8, "100")
        self.power(seconds + 13, "100")
        self.assertEqual(self.store.active("p")["source"], "automatic")

    def test_missing_power_blocks_even_without_detector(self):
        self.assert_blocked_after_end(self.start())

    def test_high_power_blocks(self):
        record = self.start()
        self.power(10, "100")
        self.assert_blocked_after_end(record)

    def test_threshold_power_is_not_low(self):
        record = self.start()
        self.power(10, "10")
        self.assert_blocked_after_end(record)

    def test_stale_low_power_blocks(self):
        record = self.start()
        self.power(10, "0")
        self.assert_blocked_after_end(record, 71)

    def test_future_low_power_blocks(self):
        record = self.start()
        self.power(21, "0")
        self.assert_blocked_after_end(record)

    def test_unavailable_invalidates_previous_low(self):
        record = self.start()
        self.power(10, "0")
        self.power(11, "unavailable")
        self.assert_blocked_after_end(record)

    def test_energy_interruption_invalidates_previous_low(self):
        record = self.start()
        self.power(10, "0")
        self.store.apply("energy", "p", self.at + timedelta(seconds=11), None)
        self.store.apply("energy", "p", self.at + timedelta(seconds=12), Decimal(100))
        self.assert_blocked_after_end(record)

    def test_synthetic_initial_low_is_not_evidence(self):
        record = self.start()
        self.power(10, "0", detection_evidence=False)
        self.assert_blocked_after_end(record)

    def test_synthetic_timer_does_not_refresh_old_evidence(self):
        record = self.start()
        self.power(2, "0")
        self.power(70, "0", detection_evidence=False)
        self.assert_blocked_after_end(record, 71)

    def test_restart_invalidates_persisted_low(self):
        record = self.start()
        self.power(10, "0")
        self.store.ledger.close()
        self.store = RuntimeStore(
            str(Path(self.tmp.name) / "ledger.sqlite3"), "CNY", "UTC"
        )
        self.store.apply(
            "configure", {"p": self.point}, {}, self.at + timedelta(seconds=12), "UTC"
        )
        self.store.apply("energy", "p", self.at + timedelta(seconds=13), Decimal(100))
        self.power(14, "0", detection_evidence=False)
        self.assert_blocked_after_end(record)

    def test_live_source_guard_rejects_cached_low(self):
        record = self.start()
        self.power(10, "0")
        self.assert_blocked_after_end(record, source_available=False)

    def test_queued_older_high_cannot_backdate_next_cycle(self):
        record = self.start()
        self.power(10, "0")
        self.end(record)
        self.power(15, "100")
        self.assertIsNone(self.store.snapshot()["points"][0]["candidate"])
        self.power(21, "100")
        self.power(26, "100")
        self.assertEqual(
            self.store.active("p")["start"],
            (self.at + timedelta(seconds=21)).isoformat(),
        )

    def test_pending_end_explicit_end_then_retry_preserves_next_cycle(self):
        self.power(0, "100")
        self.power(5, "100")
        record = self.store.active("p")
        self.power(10, "0")
        self.assertEqual(
            self.store.snapshot()["points"][0]["detection_state"], "pending_end"
        )
        self.end(record)
        self.assertIsNone(self.store.snapshot()["points"][0]["candidate"])
        self.power(21, "100")
        before = self.store.states["p"]["detector"].copy()
        self.end(record, 23)
        self.assertEqual(self.store.states["p"]["detector"], before)
        self.power(26, "100")
        self.assertNotEqual(self.store.active("p")["id"], record["id"])

    def test_automatic_confirmation_wins_before_manual_start(self):
        self.power(0, "100")
        self.power(5, "100")
        record = self.store.active("p")
        with self.assertRaises(ValueError):
            self.start(6)
        self.assertEqual(self.store.active("p")["id"], record["id"])

    def test_snapshot_disabled_precedes_manual_and_unavailable(self):
        self.point["detection"]["enabled"] = False
        self.store.apply("configure", {"p": self.point}, {}, self.at, "UTC")
        self.start()
        self.store.apply("energy", "p", self.at + timedelta(seconds=2), None)
        point = self.store.snapshot()["points"][0]
        self.assertEqual(point["recording_state"], "manual")
        self.assertEqual(point["detection_state"], "disabled")

    def test_synthetic_low_cannot_release_blocked_latch(self):
        record = self.start()
        self.power(10, "100")
        self.end(record)
        self.power(21, "0", detection_evidence=False)
        self.power(22, "100")
        self.power(27, "100")
        self.assertIsNone(self.store.active("p"))

    def test_source_or_detection_change_invalidates_low_evidence(self):
        for index, changed in enumerate(("power_entity", "detection")):
            with self.subTest(changed=changed):
                record = self.command(
                    "start", 1 + index * 30, point_id="p", request_id=changed
                )
                self.power(10 + index * 30, "0")
                if changed == "power_entity":
                    self.point["power_entity"] = "sensor.other"
                else:
                    self.point["detection"]["end_w"] = 20
                self.store.apply(
                    "configure",
                    {"p": self.point},
                    {},
                    self.at + timedelta(seconds=11 + index * 30),
                    "UTC",
                )
                self.store.apply(
                    "energy",
                    "p",
                    self.at + timedelta(seconds=12 + index * 30),
                    Decimal(100),
                )
                self.command(
                    "end",
                    20 + index * 30,
                    record_id=record["id"],
                    request_id="end-" + changed,
                )
                self.assertEqual(
                    self.store.snapshot()["points"][0]["detection_state"], "blocked"
                )
                self.store.states["p"].update(
                    power_event=None, power_event_at=None, detector=None
                )

    def test_freshness_limit_includes_exact_max_gap(self):
        record = self.start()
        self.power(10, "0")
        self.end(record, 70)
        self.assertEqual(
            self.store.snapshot()["points"][0]["detection_state"], "waiting"
        )

    def test_queued_pre_start_low_cannot_supply_new_evidence(self):
        record = self.start(20)
        self.power(10, "0")
        self.assert_blocked_after_end(record, 30)
