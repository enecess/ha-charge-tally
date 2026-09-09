"""Query intersections conserve manual energy and explicit total fees."""
from datetime import timedelta
from decimal import Decimal

import unittest
import test_accounting as fixtures
from custom_components.charge_tally.queries import summarize


T = fixtures.T


class QueryTests(unittest.TestCase):
    setUp = fixtures.AccountingTests.setUp
    manual = fixtures.AccountingTests.manual
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
        result = summarize(self.ledger, T - timedelta(seconds=5), T + timedelta(days=1))
        self.assertEqual([b['local_date'] for b in result['buckets']], ['2025-12-31', '2026-01-01'])
        self.assertTrue(result['buckets'][0]['cost_complete'])
        self.assertFalse(result['buckets'][1]['cost_complete'])
        self.assertIn('pending_settlement', result['buckets'][1]['quality'])
        self.assertEqual(Decimal(result['buckets'][1]['energy_kwh']), 0)
