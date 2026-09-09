from datetime import datetime, timedelta
from decimal import Decimal
import json
import unittest

from custom_components.charge_tally.core.detection import Detector


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime.fromisoformat('2026-01-01T00:00:00+00:00')
        self.detector = Detector(Decimal(100), Decimal(10), 30, 300)

    def observe(self, seconds, power, identity='alice'):
        return self.detector.observe(self.start + timedelta(seconds=seconds), None if power is None else Decimal(power), identity)

    def test_start_identity_and_end_backdating(self):
        self.assertEqual(self.observe(0, 100), [])
        self.assertEqual(self.detector.state, 'pending_start')
        self.assertEqual(self.observe(29, 100, 'bob'), [])
        self.assertEqual(self.observe(30, 100, 'bob'), [{'kind': 'start', 'at': self.start.isoformat(), 'identity_id': 'alice'}])
        self.observe(40, 0)
        self.assertEqual(self.observe(339, 0), [])
        self.assertEqual(self.observe(340, 0), [{'kind': 'end', 'at': (self.start + timedelta(seconds=40)).isoformat(), 'identity_id': 'alice'}])

    def test_pause_merge_and_unavailable_break_continuity(self):
        self.observe(0, 100)
        self.observe(20, None)
        self.assertEqual(self.observe(30, 100), [])
        self.assertEqual(len(self.observe(60, 100)), 1)
        self.observe(70, 0)
        self.observe(100, 10)
        self.assertEqual(self.detector.state, 'charging')
        self.observe(110, 0)
        self.observe(300, None)
        self.observe(410, 0)
        self.assertEqual(self.observe(709, 0), [])
        self.assertEqual(len(self.observe(710, 0)), 1)

    def test_restore_interruption_and_force_stop_latch(self):
        self.observe(0, 100)
        self.detector.restore(json.loads(json.dumps(self.detector.snapshot())))
        self.assertEqual(self.observe(1000, 100, 'bob'), [])
        self.assertEqual(self.observe(1030, 100, 'bob')[0]['identity_id'], 'bob')
        self.observe(1040, 0)
        self.detector.restore(self.detector.snapshot())
        self.assertEqual(self.detector.state, 'charging')
        self.assertEqual(self.observe(2000, 0), [])
        self.assertEqual(self.observe(2300, 0)[0]['identity_id'], 'bob')
        self.detector.force_stop()
        self.assertEqual(self.observe(2400, 100), [])
        self.assertEqual(self.observe(2500, 100), [])
        self.observe(2501, 0)
        self.observe(2502, 100)
        self.assertEqual(len(self.observe(2532, 100)), 1)

    def test_uninterrupted_restore_preserves_candidate(self):
        self.observe(0, 100)
        self.detector.restore(self.detector.snapshot(), interrupted=False)
        self.assertEqual(len(self.observe(30, 100)), 1)

    def test_rejects_configuration_and_out_of_order(self):
        for args in [(10, 10, 30, 300), (100, -1, 30, 300), (100, 10, 0, 300), (100, 10, float('nan'), 300)]:
            with self.assertRaises(ValueError):
                Detector(*args)
        self.observe(30, 100)
        with self.assertRaises(ValueError):
            self.observe(0, 100)
