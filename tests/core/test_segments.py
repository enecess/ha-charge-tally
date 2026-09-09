from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo
import unittest

from custom_components.charge_tally.core.segments import split_interval


class SegmentTests(unittest.TestCase):
    def test_year_boundary(self):
        start = datetime.fromisoformat('2026-12-31T23:59:50+08:00')
        parts = split_interval(start, start + timedelta(seconds=30), Decimal('.060'), 'Asia/Shanghai', [(start, Decimal('1'))])
        self.assertEqual([Decimal(p['energy_kwh']) for p in parts], [Decimal('.020'), Decimal('.040')])
        self.assertEqual([p['local_date'] for p in parts], ['2026-12-31', '2027-01-01'])

    def test_prices_unknown_zero_negative_and_conservation(self):
        start = datetime.fromisoformat('2026-01-01T00:00:00+00:00')
        prices = [(start + timedelta(seconds=i), p) for i, p in [(1, Decimal('0')), (2, Decimal('-2')), (3, None)]]
        parts = split_interval(start, start + timedelta(seconds=4), Decimal('1'), 'UTC', prices)
        self.assertEqual([None if p['cost'] is None else Decimal(p['cost']) for p in parts], [None, Decimal(0), Decimal('-.5'), None])
        self.assertTrue(all('price_unknown' in p['quality'] for p in [parts[0], parts[3]]))
        self.assertEqual(sum(Decimal(p['energy_kwh']) for p in parts), 1)

    def test_dst_actual_duration(self):
        tz = ZoneInfo('America/New_York')
        for day, hours in [('2026-03-08', 23), ('2026-11-01', 25)]:
            start = datetime.fromisoformat(day).replace(tzinfo=tz)
            parts = split_interval(start, start + timedelta(days=2), Decimal(hours + 24), tz.key, [(start, Decimal(1))])
            self.assertEqual([Decimal(p['energy_kwh']) for p in parts], [Decimal(hours), Decimal(24)])

    def test_timeline_validation_and_idempotent_duplicate(self):
        start = datetime.fromisoformat('2026-01-01T00:00:00+00:00')
        end = start + timedelta(seconds=3)
        for prices in [[(end, Decimal(1)), (start, Decimal(1))], [(start, Decimal(1)), (start, Decimal(2))], [(start, Decimal('NaN'))]]:
            with self.assertRaises(ValueError):
                split_interval(start, end, Decimal(1), 'UTC', prices)
        parts = split_interval(start, end, Decimal(1), 'UTC', [(start, Decimal(1)), (start, Decimal(1))], [start + timedelta(seconds=1), start + timedelta(seconds=2)])
        with localcontext() as ctx:
            ctx.prec = 36
            self.assertEqual(sum(Decimal(p['energy_kwh']) for p in parts), 1)
        for left, right, energy in [(end, start, Decimal(1)), (start, end, Decimal('-1')), (start.replace(tzinfo=None), end, Decimal(1))]:
            with self.assertRaises(ValueError):
                split_interval(left, right, energy, 'UTC', [])
