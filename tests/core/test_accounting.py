"""Record lifecycle, historical previews and mutable accounting."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from custom_components.charge_tally.ledger import Ledger
from custom_components.charge_tally.accounting import Accounting
from custom_components.charge_tally.queries import summarize

D = Decimal
T = datetime(2026, 1, 1, tzinfo=timezone.utc)


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.ledger = Ledger(str(Path(self.directory.name) / 'db'))
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.ledger.close)
        for identity in ('personal', 'company'):
            self.ledger.put_identity({'id': identity, 'name': identity})
        for point in ('home', 'work'):
            self.ledger.put_point({'id': point, 'name': point})
        self.app = Accounting(self.ledger)

    def interval(self, start=T, end=T + timedelta(seconds=30), energy='0.060'):
        self.app.add_interval('home', start, end, D(energy), [(start, D('1'))])

    def manual(self, **changes):
        data = dict(point_id='home', identity_id='personal', start=T, end=T + timedelta(hours=3),
                    timezone='UTC', energy_kwh='21', cost=None, note='manual')
        data.update(changes)
        return data

    def test_start_conflicts_concurrency_and_idempotency(self):
        first = self.app.start('home', 'personal', T, 'start')
        self.assertEqual(first, self.app.start('home', 'personal', T, 'start'))
        with self.assertRaises(ValueError):
            self.app.start('home', 'company', T, 'another')
        with self.assertRaises(ValueError):
            self.app.start('work', 'company', T, 'start')
        self.app.start('work', 'company', T, 'work')
        with self.assertRaises(ValueError):
            self.app.start('unknown', 'personal', T, 'unknown')
        self.assertEqual(summarize(self.ledger, None, None)['active_count'], 2)

    def test_transfer_void_revision_and_backdating(self):
        first = self.app.start('home', 'personal', T, 'start')
        self.interval()
        current = self.ledger.get_record(first['id'])
        moved = self.app.reassign(first['id'], 'company', current['revision'])
        self.assertEqual(D(summarize(self.ledger, None, None, identity_id='personal')['energy_kwh']), 0)
        self.assertEqual(D(summarize(self.ledger, None, None, identity_id='company')['energy_kwh']), D('.060'))
        with self.assertRaises(ValueError):
            self.app.reassign(first['id'], 'personal', current['revision'])
        ended = self.app.end(first['id'], T + timedelta(seconds=10), 'end')
        self.assertEqual(D(ended['energy_kwh']), D('.020'))
        self.assertEqual(self.app.end(first['id'], T + timedelta(seconds=10), 'end'), ended)
        self.app.void(first['id'], ended['revision'])
        self.assertEqual(D(summarize(self.ledger, None, None)['energy_kwh']), 0)
        self.assertGreaterEqual(len(self.ledger.list_revisions(first['id'])), 4)

    def test_pending_adjacent_records_and_interval_dedup(self):
        first = self.app.start('home', 'personal', T, 'first')
        ended = self.app.end(first['id'], T + timedelta(seconds=10), 'end')
        self.assertIn('pending_settlement', ended['quality'])
        second = self.app.start('home', 'company', T + timedelta(seconds=10), 'second')
        self.interval()
        self.interval()
        self.assertEqual(D(self.ledger.get_record(first['id'])['energy_kwh']), D('.020'))
        self.assertNotIn('pending_settlement', self.ledger.get_record(first['id'])['quality'])
        self.assertEqual(D(self.ledger.get_record(second['id'])['energy_kwh']), D('.040'))
        self.assertEqual(D(summarize(self.ledger, None, None)['energy_kwh']), D('.060'))

    def test_manual_preview_unknown_and_override(self):
        self.interval()
        preview = self.app.preview(self.manual(start=T - timedelta(hours=1), end=T + timedelta(hours=2)))
        self.assertEqual([D(s['energy_kwh']) for s in preview['segments']], [D(7), D(14)])
        self.assertIsNone(preview['segments'][0]['cost'])
        self.assertFalse(preview['record']['cost_complete'])
        result = self.app.commit_preview(preview['token'], 'manual')
        self.assertEqual(D(result['energy_kwh']), 21)
        self.assertEqual(result, self.app.commit_preview(preview['token'], 'manual'))
        self.assertEqual(D(summarize(self.ledger, None, None)['energy_kwh']), 21)

    def test_preview_conflict_and_historical_edit(self):
        data = self.manual(cost='42')
        preview = self.app.preview(data)
        self.ledger.put_point({'id': 'home', 'name': 'Changed'})
        with self.assertRaises(ValueError):
            self.app.commit_preview(preview['token'], 'stale')
        result = self.app.commit_preview(self.app.preview(data)['token'], 'save')
        overlap = self.app.preview(data)
        self.assertEqual(overlap['overlaps'], [result['id']])
        with self.assertRaises(ValueError):
            self.app.commit_preview(overlap['token'], 'overlap')
        edit = self.manual(record_id=result['id'], expected_revision=result['revision'], energy_kwh='3', cost='6')
        updated = self.app.commit_preview(self.app.preview(edit)['token'], 'edit')
        self.assertEqual(D(updated['energy_kwh']), 3)
        self.assertEqual(D(summarize(self.ledger, None, None)['known_cost']), 6)

    def test_history_missing_energy_gap_and_retention(self):
        first = self.app.start('home', 'personal', T, 'start')
        self.interval(end=T + timedelta(hours=1), energy='7')
        result = self.ledger.get_record(first['id'])
        self.assertEqual(D(result['energy_kwh']), 0)
        self.assertIn('missing_energy', result['quality'])
        self.ledger.prune(T + timedelta(days=100))
        self.assertEqual(len(self.ledger.list_intervals('home')), 1)

    def test_historical_preview_uses_retained_intervals(self):
        self.interval()
        data = self.manual(end=T + timedelta(seconds=30))
        del data['energy_kwh']
        del data['cost']
        preview = self.app.preview(data)
        self.assertEqual(D(preview['record']['energy_kwh']), D('.060'))
        self.assertEqual(D(preview['record']['known_cost']), D('.060'))
        self.assertEqual(preview['coverage'], [{'start': T.isoformat(), 'end': (T + timedelta(seconds=30)).isoformat()}])
        self.app.commit_preview(preview['token'], 'history')

    def test_manual_energy_uses_observed_price_without_double_counting(self):
        self.interval()
        data = self.manual(end=T + timedelta(seconds=30))
        del data['cost']
        preview = self.app.preview(data)
        self.assertEqual(D(preview['record']['known_cost']), 21)
        self.assertTrue(preview['record']['cost_complete'])

    def test_record_and_request_roll_back_with_enclosing_checkpoint_transaction(self):
        with self.assertRaises(ValueError):
            with self.ledger.transaction():
                self.app.start('home', 'personal', T, 'start')
                self.ledger.put_checkpoint('home', {'last_at': T.isoformat()})
                raise ValueError('Injected runtime checkpoint failure')
        self.assertEqual(self.ledger.list_records(), [])
        self.assertIsNone(self.ledger.get_request('start'))
        self.assertIsNone(self.ledger.get_checkpoint('home'))
        record = self.app.start('home', 'personal', T, 'start')
        self.interval()
        revisions = self.ledger.list_revisions(record['id'])
        bad = self.ledger.get_record(record['id'])
        bad['revision'] += 1
        segment = dict(self.ledger.list_segments(record['id'])[0], observation_id='missing')
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.save_record(bad, [segment])
        self.assertEqual(self.ledger.list_revisions(record['id']), revisions)
        self.assertEqual(D(self.ledger.get_record(record['id'])['energy_kwh']), D('.060'))

    def test_retention_preserves_revision_observations_and_prunes_unclaimed(self):
        self.interval()
        data = self.manual(end=T + timedelta(seconds=30))
        del data['energy_kwh']
        del data['cost']
        record = self.app.commit_preview(self.app.preview(data)['token'], 'history')
        edit = self.manual(record_id=record['id'], expected_revision=record['revision'],
                           start=T + timedelta(hours=1), end=T + timedelta(hours=2))
        self.app.commit_preview(self.app.preview(edit)['token'], 'move')
        self.interval(start=T + timedelta(seconds=30), end=T + timedelta(seconds=60))
        self.assertEqual(self.ledger.prune(T + timedelta(days=100)), 1)
        self.assertEqual(len(self.ledger.list_intervals('home')), 1)

    def test_active_edits_and_future_history_rejected(self):
        record = self.app.start('home', 'personal', T, 'start')
        with self.assertRaises(ValueError):
            self.app.preview(self.manual(record_id=record['id'], expected_revision=record['revision']))
        with self.assertRaises(ValueError):
            self.app.preview(self.manual(end=datetime.now(timezone.utc) + timedelta(days=1)))

    def test_identity_note_preview_preserves_manual_pricing(self):
        data = self.manual(end=T + timedelta(seconds=30), prices=[(T, '1')])
        del data['cost']
        record = self.app.commit_preview(self.app.preview(data)['token'], 'save')
        self.ledger.put_price_version({'id': 'new', 'point_id': 'home', 'at': T.isoformat(), 'price': '2'})
        edit = self.app.preview({'record_id': record['id'], 'expected_revision': record['revision'],
                                 'identity_id': 'company', 'note': 'corrected'})
        changed = self.app.commit_preview(edit['token'], 'edit')
        self.assertEqual(changed['known_cost'], record['known_cost'])
        self.assertEqual(changed['note'], 'corrected')

    def test_observed_gap_can_be_replaced_by_validated_history(self):
        record = self.app.start('home', 'personal', T, 'start')
        self.interval(end=T + timedelta(hours=1), energy='6')
        self.assertIn('missing_energy', self.ledger.get_record(record['id'])['quality'])
        self.app.replace_gap('home', T, T + timedelta(hours=1), [
            {'start': T + timedelta(minutes=n), 'end': T + timedelta(minutes=n + 10),
             'energy_kwh': '1', 'prices': [(T, '1')]} for n in range(0, 60, 10)])
        restored = self.ledger.get_record(record['id'])
        self.assertEqual(D(restored['energy_kwh']), 6)
        self.assertNotIn('missing_energy', restored['quality'])

    def test_manual_fee_edit_preserves_measured_energy(self):
        self.interval()
        data = self.manual(end=T + timedelta(seconds=30))
        del data['energy_kwh']
        del data['cost']
        record = self.app.commit_preview(self.app.preview(data)['token'], 'save')
        edit = self.app.preview({'record_id': record['id'], 'expected_revision': record['revision'], 'cost': '5'})
        changed = self.app.commit_preview(edit['token'], 'edit')
        self.assertEqual(D(changed['energy_kwh']), D('.060'))
        self.assertEqual(D(changed['known_cost']), 5)

    def test_static_price_outlives_meter_observation_coverage(self):
        self.ledger.put_price_version({'id': 'static', 'point_id': 'home', 'at': T.isoformat(), 'price': '2'})
        self.app.add_interval('home', T, T + timedelta(seconds=10), D('1'), [(T, D('2'))])
        data = self.manual(end=T + timedelta(seconds=30), energy_kwh='3')
        del data['cost']
        result = self.app.preview(data)['record']
        self.assertEqual(D(result['known_cost']), 6)
        self.assertTrue(result['cost_complete'])

    def test_manual_preview_ignores_unrelated_observations_and_prices(self):
        preview = self.app.preview(self.manual(cost='6'))
        self.app.add_interval('work', T, T + timedelta(seconds=10), D(1), [])
        self.interval(start=T + timedelta(days=1), end=T + timedelta(days=1, seconds=30))
        self.ledger.put_price_version({'id': 'later', 'point_id': 'home', 'at': (T + timedelta(days=1)).isoformat(), 'price': '2'})
        record = self.app.commit_preview(preview['token'], 'save')
        self.assertEqual(D(record['known_cost']), 6)

    def test_history_preview_rejects_changed_relevant_interval(self):
        data = self.manual(end=T + timedelta(seconds=30))
        del data['energy_kwh']
        del data['cost']
        preview = self.app.preview(data)
        self.interval()
        with self.assertRaises(ValueError):
            self.app.commit_preview(preview['token'], 'stale')

    def test_manual_price_preview_rejects_relevant_price_change_only(self):
        data = self.manual(end=T + timedelta(seconds=30))
        del data['cost']
        preview = self.app.preview(data)
        self.ledger.put_price_version({'id': 'later', 'point_id': 'home', 'at': (T + timedelta(days=1)).isoformat(), 'price': '2'})
        self.app.commit_preview(preview['token'], 'unrelated-price')
        data['point_id'] = 'work'
        preview = self.app.preview(data)
        self.ledger.put_price_version({'id': 'inside', 'point_id': 'work', 'at': T.isoformat(), 'price': '2'})
        with self.assertRaises(ValueError):
            self.app.commit_preview(preview['token'], 'relevant-price')

    def test_inactive_references_allow_existing_history_metadata(self):
        record = self.app.commit_preview(self.app.preview(self.manual())['token'], 'save')
        self.ledger.put_identity({'id': 'personal', 'name': 'personal', 'active': False})
        self.ledger.put_point({'id': 'home', 'name': 'home', 'active': False})
        preview = self.app.preview({'record_id': record['id'], 'expected_revision': record['revision'], 'note': 'archived note'})
        changed = self.app.commit_preview(preview['token'], 'note')
        self.assertEqual(changed['note'], 'archived note')
        with self.assertRaises(ValueError):
            self.app.start('home', 'company', T + timedelta(days=1), 'disabled-point')
        with self.assertRaises(ValueError):
            self.app.start('work', 'personal', T + timedelta(days=1), 'disabled-identity')
        other = self.app.start('work', 'company', T + timedelta(days=1), 'other')
        with self.assertRaises(ValueError):
            self.app.reassign(other['id'], 'personal', other['revision'])
