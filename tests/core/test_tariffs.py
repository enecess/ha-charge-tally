from datetime import datetime
from decimal import Decimal
import unittest

from custom_components.charge_tally.core.tariffs import DailySchedule
from custom_components.charge_tally.core.segments import split_interval


class TariffTests(unittest.TestCase):
    def schedule(self):
        return DailySchedule([{'start': '22:00', 'end': '08:00', 'price': '-1'},
                              {'start': '08:00', 'end': '22:00', 'price': '2'}])

    def test_overnight_and_left_closed(self):
        for hour, price in [(0, -1), (7, -1), (8, 2), (21, 2), (22, -1)]:
            self.assertEqual(self.schedule().price_at(datetime.fromisoformat(f'2026-01-01T{hour:02}:00:00+08:00'), 'Asia/Shanghai'), price)

    def test_rejects_gap_overlap_and_invalid(self):
        for rows in [[], [{'start': '08:00', 'end': '22:00', 'price': '1'}],
                     [{'start': '00:00', 'end': '24:00', 'price': '1'}, {'start': '08:00', 'end': '09:00', 'price': '1'}],
                     [{'start': '00:00', 'end': '24:00', 'price': 'NaN'}]]:
            with self.assertRaises(ValueError):
                DailySchedule(rows)

    def test_fallback_has_both_occurrences(self):
        schedule = DailySchedule([{'start': '00:00', 'end': '01:30', 'price': '1'},
                                  {'start': '01:30', 'end': '24:00', 'price': '2'}])
        boundaries = schedule.boundaries(datetime.fromisoformat('2026-11-01T04:00:00+00:00'), datetime.fromisoformat('2026-11-02T05:00:00+00:00'), 'America/New_York')
        self.assertIn(datetime.fromisoformat('2026-11-01T05:30:00+00:00'), boundaries)
        self.assertIn(datetime.fromisoformat('2026-11-01T06:30:00+00:00'), boundaries)
        self.assertIn(datetime.fromisoformat('2026-11-01T06:00:00+00:00'), boundaries)

    def test_fallback_pricing_repeats_local_schedule(self):
        schedule = DailySchedule([{'start': '00:00', 'end': '01:30', 'price': '1'},
                                  {'start': '01:30', 'end': '24:00', 'price': '2'}])
        start = datetime.fromisoformat('2026-11-01T04:00:00+00:00')
        end = datetime.fromisoformat('2026-11-02T05:00:00+00:00')
        changes = [start, *schedule.boundaries(start, end, 'America/New_York')]
        parts = split_interval(start, end, Decimal(25), 'America/New_York',
                               [(at, schedule.price_at(at, 'America/New_York')) for at in changes])
        self.assertEqual([Decimal(p['energy_kwh']) for p in parts], [Decimal('1.5'), Decimal('.5'), Decimal('.5'), Decimal('22.5')])
        self.assertEqual(sum(Decimal(p['cost']) for p in parts), Decimal(48))

    def test_spring_nonexistent_boundary_applies_at_clock_jump(self):
        schedule = DailySchedule([{'start': '00:00', 'end': '02:30', 'price': '1'},
                                  {'start': '02:30', 'end': '24:00', 'price': '2'}])
        start = datetime.fromisoformat('2026-03-08T05:00:00+00:00')
        end = datetime.fromisoformat('2026-03-09T04:00:00+00:00')
        boundaries = schedule.boundaries(start, end, 'America/New_York')
        self.assertEqual(boundaries, [datetime.fromisoformat('2026-03-08T07:00:00+00:00')])
        self.assertEqual(schedule.price_at(boundaries[0], 'America/New_York'), Decimal(2))
