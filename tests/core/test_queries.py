"""Query intersections conserve manual energy and explicit total fees."""
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

import unittest
from unittest.mock import patch
import test_accounting as fixtures
from custom_components.charge_tally.queries import summarize


T = fixtures.T


class QueryTests(unittest.TestCase):
    setUp = fixtures.AccountingTests.setUp
    manual = fixtures.AccountingTests.manual
    def test_hour_boundaries_are_reused_within_each_summary(self):
        from custom_components.charge_tally.core.buckets import calendar_boundaries
        record = self.app.start('home', 'personal', T, 'start')
        segments = [dict(start=(T+timedelta(seconds=5*i)).isoformat(),
                         end=(T+timedelta(seconds=5*(i+1))).isoformat(),
                         energy_kwh='0.001', cost='0.0005', quality=[]) for i in range(7200)]
        self.ledger.save_record(record, segments, audit=False)
        with patch('custom_components.charge_tally.core.buckets.calendar_boundaries', wraps=calendar_boundaries) as boundaries:
            first = summarize(self.ledger, T, T+timedelta(hours=10))
            self.assertEqual(boundaries.call_count, 1)
            second = summarize(self.ledger, T, T+timedelta(hours=10))
            self.assertEqual(boundaries.call_count, 2)
        self.assertEqual(first, second)
        self.assertEqual(Decimal(first['energy_kwh']), Decimal('7.200'))
        self.assertEqual(Decimal(first['known_cost']), Decimal('3.6000'))
        self.assertEqual(len(first['buckets']), 10)

    def test_hourly_distribution_uses_raw_detail(self):
        self.app.start('home', 'personal', T, 'start')
        self.ledger.put_point({**self.ledger.get_point('home'), 'max_interval_seconds': 7200})
        self.app.add_interval('home', T, T + timedelta(hours=1), Decimal('1'), [(T, Decimal('2'))])
        self.app.add_interval('home', T + timedelta(hours=1), T + timedelta(hours=2), Decimal('9'), [])
        result = summarize(self.ledger, None, None, calendar='2026-01-01', bucket_period='hour')
        self.assertEqual([Decimal(b['energy_kwh']) for b in result['buckets']], [1, 9])
        self.assertEqual(Decimal(result['energy_kwh']), 10)
        self.assertTrue(result['buckets'][0]['cost_complete'])
        self.assertFalse(result['buckets'][1]['has_known_cost'])
        self.assertTrue(result['has_energy_data'])
        self.assertEqual(result['matched_count'], 1)

    def test_clipped_manual_cost_and_counts(self):
        preview = self.app.preview(self.manual(start=T - timedelta(hours=1), end=T + timedelta(hours=2), cost='-6'))
        self.app.commit_preview(preview['token'], 'manual')
        result = summarize(self.ledger, T, T + timedelta(hours=1))
        self.assertEqual(Decimal(result['energy_kwh']), 7)
        self.assertEqual(Decimal(result['known_cost']), -2)
        self.assertTrue(result['cost_complete'])
        self.assertEqual(result['completed_count'], 0)
        self.assertIn('estimated', result['quality'])
        self.assertEqual(len(result['buckets']), 1)

    def test_price_gap_outside_query_does_not_poison_complete_range(self):
        record = self.app.start('home', 'personal', T, 'start')
        self.app.add_interval('home', T, T + timedelta(seconds=30), Decimal('3'),
                              [(T, Decimal('1')), (T + timedelta(seconds=10), None)])
        self.app.end(record['id'], T + timedelta(seconds=30), 'end')
        result = summarize(self.ledger, T, T + timedelta(seconds=10))
        self.assertTrue(result['cost_complete'])
        self.assertNotIn('missing_price', result['quality'])
        self.assertEqual(Decimal(result['known_cost']), 1)

    def test_energy_gap_outside_query_does_not_poison_complete_range(self):
        record = self.app.start('home', 'personal', T, 'start')
        self.app.add_interval('home', T, T + timedelta(seconds=10), Decimal('1'), [(T, Decimal('1'))])
        self.app.end(record['id'], T + timedelta(seconds=30), 'end')
        complete = summarize(self.ledger, T, T + timedelta(seconds=10))
        self.assertTrue(complete['cost_complete'])
        missing = summarize(self.ledger, T + timedelta(seconds=10), T + timedelta(seconds=20))
        self.assertFalse(missing['cost_complete'])
        self.assertIn('missing_energy', missing['quality'])

    def test_buckets_include_pending_and_entirely_missing_local_dates(self):
        start = T - timedelta(seconds=10)
        record = self.app.start('home', 'personal', start, 'start', timezone='UTC')
        self.app.add_interval('home', start, T, Decimal(1), [(start, Decimal(1))])
        active = summarize(self.ledger, None, None)
        self.assertIn('provisional', active['buckets'][0]['quality'])
        self.app.end(record['id'], T + timedelta(days=1), 'end')
        result = summarize(self.ledger, T - timedelta(seconds=5), T + timedelta(days=1), bucket_period='day')
        self.assertEqual([b['key'] for b in result['buckets']], ['2025-12-31', '2026-01-01'])
        self.assertTrue(result['buckets'][0]['cost_complete'])
        self.assertFalse(result['buckets'][1]['cost_complete'])
        self.assertIn('pending_settlement', result['buckets'][1]['quality'])
        self.assertEqual(Decimal(result['buckets'][1]['energy_kwh']), 0)


    def test_calendar_missing_energy_and_active_overlap_preserve_completed_start_date(self):
        record = self.app.start('home', 'personal', T - timedelta(hours=9), 'start', timezone='Asia/Shanghai')
        self.app.add_interval('home', T - timedelta(hours=9), T + timedelta(hours=1), Decimal('10'), [])
        result = summarize(self.ledger, None, None, calendar='2026-01-01', bucket_period='day')
        self.assertEqual(result['active_count'], 1)
        self.assertFalse(result['cost_complete'])
        self.assertIn('missing_energy', result['quality'])
        self.assertEqual([b['key'] for b in result['buckets']], ['2026-01-01'])
        self.app.end(record['id'], T + timedelta(hours=2), 'end')
        result = summarize(self.ledger, None, None, calendar='2026-01-01')
        self.assertEqual(result['completed_count'], 0)
        self.assertFalse(result['cost_complete'])
        with self.assertRaises(ValueError):
            summarize(self.ledger, T, None, calendar='2026-01-01')


    def test_calendar_cross_year_uses_segments_and_counts_once(self):
        preview = self.app.preview(self.manual(start=T-timedelta(hours=9), end=T-timedelta(hours=6), cost='21', timezone='Asia/Shanghai'))
        self.app.commit_preview(preview['token'], 'calendar')
        for label, energy, count in [('2025', 7, 1), ('2025-12', 7, 1), ('2025-12-31', 7, 1), ('2026', 14, 0), ('2026-01', 14, 0), ('2026-01-01', 14, 0)]:
            result = summarize(self.ledger, None, None, calendar=label)
            self.assertEqual(Decimal(result['energy_kwh']), energy)
            self.assertEqual(Decimal(result['known_cost']), energy)
            self.assertEqual(result['completed_count'], count)


    def test_calendar_counts_records_without_any_energy_segments(self):
        record = self.app.start('home', 'personal', T - timedelta(hours=8), 'start', timezone='Asia/Shanghai')
        result = summarize(self.ledger, None, None, calendar='2026-01-01')
        self.assertEqual(result['active_count'], 1)
        self.assertEqual(result['energy_kwh'], '0')
        self.app.end(record['id'], T, 'end')
        result = summarize(self.ledger, None, None, calendar='2026-01-01')
        self.assertEqual(result['completed_count'], 1)
        self.assertFalse(result['cost_complete'])
        self.assertIn('missing_energy', result['quality'])


    def test_calendar_active_record_from_previous_day_includes_today_energy(self):
        self.app.start('home', 'personal', T - timedelta(hours=9), 'start', timezone='Asia/Shanghai')
        start = T - timedelta(hours=8)
        self.app.add_interval('home', start, start + timedelta(seconds=30), Decimal('1'), [(start, Decimal('2'))])
        result = summarize(self.ledger, None, None, calendar='2026-01-01')
        self.assertEqual(result['active_count'], 1)
        self.assertEqual(result['completed_count'], 0)
        self.assertEqual(Decimal(result['energy_kwh']), 1)
        self.assertEqual(Decimal(result['known_cost']), 2)

    def test_empty_pending_and_real_zero_are_distinct(self):
        empty = summarize(self.ledger, None, None)
        self.assertEqual(empty['matched_count'], 0)
        self.assertFalse(empty['has_energy_data'])
        self.app.start('home', 'personal', T, 'start')
        pending = summarize(self.ledger, None, None)
        self.assertEqual(pending['matched_count'], 1)
        self.assertFalse(pending['has_energy_data'])
        self.assertFalse(pending['has_known_cost'])
        self.app.add_interval('home', T, T+timedelta(seconds=30), Decimal(0), [(T, Decimal(0))])
        zero = summarize(self.ledger, None, None)
        self.assertTrue(zero['has_energy_data'])
        self.assertTrue(zero['has_known_cost'])
        self.assertEqual(Decimal(zero['energy_kwh']), 0)
        self.assertTrue(zero['buckets'][0]['has_known_cost'])

    def test_mixed_timezones_keep_hour_identity_and_merge_calendar_labels(self):
        for point, zone in [('home', 'UTC'), ('work', 'Asia/Shanghai')]:
            preview = self.app.preview(self.manual(point_id=point, start=T, end=T+timedelta(hours=1), timezone=zone, energy_kwh='1', cost='0'))
            self.app.commit_preview(preview['token'], point)
        hours = summarize(self.ledger, None, None, calendar='2026-01-01')
        self.assertEqual(len(hours['buckets']), 2)
        self.assertEqual(len({b['key'] for b in hours['buckets']}), 2)
        self.assertEqual({b['timezone'] for b in hours['buckets']}, {'UTC', 'Asia/Shanghai'})
        for period, key in [('day', '2026-01-01'), ('month', '2026-01'), ('year', '2026')]:
            result = summarize(self.ledger, None, None, bucket_period=period)
            self.assertEqual([b['key'] for b in result['buckets']], [key])
            self.assertNotIn('start', result['buckets'][0])
            self.assertEqual(Decimal(result['buckets'][0]['energy_kwh']), 2)

    def test_lord_howe_manual_allocation_conserves_negative_cost(self):
        start = datetime(2026, 4, 5, tzinfo=ZoneInfo('Australia/Lord_Howe'))
        preview = self.app.preview(self.manual(start=start, end=start+timedelta(days=1), timezone='Australia/Lord_Howe', energy_kwh='1', cost='-1'))
        self.app.commit_preview(preview['token'], 'save')
        result = summarize(self.ledger, None, None, calendar='2026-04-05')
        with localcontext() as ctx:
            ctx.prec = 36
            self.assertEqual(sum(Decimal(b['energy_kwh']) for b in result['buckets']), Decimal(result['energy_kwh']))
            self.assertEqual(sum(Decimal(b['known_cost']) for b in result['buckets']), Decimal(result['known_cost']))
        short = [b for b in result['buckets'] if (datetime.fromisoformat(b['end'])-datetime.fromisoformat(b['start'])).total_seconds() == 1800]
        self.assertEqual(len(short), 1)
        self.assertAlmostEqual(float(short[0]['energy_kwh']), 1/49)
        self.assertTrue(all('estimated' in b['quality'] for b in result['buckets']))

    def test_hourly_gap_has_no_energy_data(self):
        record = self.app.start('home', 'personal', T, 'start')
        self.app.end(record['id'], T+timedelta(hours=2), 'end')
        result = summarize(self.ledger, None, None, calendar='2026-01-01')
        self.assertEqual(len(result['buckets']), 2)
        self.assertFalse(result['has_energy_data'])
        for bucket in result['buckets']:
            self.assertFalse(bucket['has_energy_data'])
            self.assertFalse(bucket['has_known_cost'])
            self.assertFalse(bucket['cost_complete'])

    def test_multiple_clipped_samples_conserve_exact_summary_totals(self):
        self.app.start('home', 'personal', T, 'start')
        self.ledger.put_point({**self.ledger.get_point('home'), 'max_interval_seconds': 7200})
        for index in range(20):
            left = T + timedelta(minutes=6*index)
            self.app.add_interval('home', left, left+timedelta(minutes=6), Decimal(1), [(left, Decimal(-1))])
        start, end = T+timedelta(minutes=1), T+timedelta(minutes=119)
        result = summarize(self.ledger, start, end, bucket_period='hour')
        expected = Decimal('19.6666666666666666666666666666666666')
        self.assertEqual(Decimal(result['energy_kwh']), expected)
        self.assertEqual(Decimal(result['known_cost']), expected.copy_negate())
        with localcontext() as ctx:
            ctx.prec = 36
            self.assertEqual(sum(Decimal(b['energy_kwh']) for b in result['buckets']), Decimal(result['energy_kwh']))
            self.assertEqual(sum(Decimal(b['known_cost']) for b in result['buckets']), Decimal(result['known_cost']))
        daily = summarize(self.ledger, start, end, bucket_period='day')
        self.assertEqual(daily['energy_kwh'], result['energy_kwh'])
        self.assertEqual(daily['known_cost'], result['known_cost'])
        self.assertTrue(all(b['has_known_cost'] and b['cost_complete'] for b in result['buckets']))
        zero_start, unknown_start, finish = (T+timedelta(hours=hour) for hour in (2, 3, 4))
        self.app.add_interval('home', zero_start, unknown_start, Decimal(0), [(zero_start, Decimal(0))])
        self.app.add_interval('home', unknown_start, finish, Decimal(1), [])
        extended = summarize(self.ledger, start, finish, bucket_period='hour')
        with localcontext() as ctx:
            ctx.prec = 36
            for field in ('energy_kwh', 'known_cost'):
                self.assertEqual(sum(Decimal(b[field]) for b in extended['buckets']), Decimal(extended[field]))
        zero, unknown = extended['buckets'][-2:]
        self.assertEqual(Decimal(zero['energy_kwh']), 0)
        self.assertEqual(Decimal(zero['known_cost']), 0)
        self.assertTrue(zero['has_known_cost'])
        self.assertTrue(zero['cost_complete'])
        self.assertEqual(Decimal(unknown['known_cost']), 0)
        self.assertFalse(unknown['has_known_cost'])
        self.assertFalse(unknown['cost_complete'])
