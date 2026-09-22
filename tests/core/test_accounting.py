"""Record lifecycle, historical previews and mutable accounting."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

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

    def test_sequential_append_preserves_previous_segment_and_revision(self):
        record = self.app.start('home', 'personal', T, 'start')
        self.interval()
        previous = self.ledger._db.execute('SELECT position,data FROM segments').fetchall()
        sql = []
        self.ledger._db.set_trace_callback(sql.append)
        self.interval(T + timedelta(seconds=30), T + timedelta(seconds=35), '.001')
        self.ledger._db.set_trace_callback(None)
        self.assertFalse(any('DELETE FROM segments' in statement for statement in sql))
        self.assertEqual(self.ledger._db.execute('SELECT position,data FROM segments WHERE position=0').fetchall(), previous)
        current = self.ledger.get_record(record['id'])
        self.assertEqual(D(current['energy_kwh']), D('.061'))
        self.assertEqual(current['revision'], 3)
        self.assertEqual(current['_segment_count'], 2)
        self.assertEqual(current['_accounted_until'], (T + timedelta(seconds=35)).isoformat())

    def test_incremental_matches_forced_full_rebuild_for_720_samples(self):
        other = Ledger(str(Path(self.directory.name) / 'full'))
        self.addCleanup(other.close)
        other.put_point({'id': 'home', 'name': 'home'})
        other.put_identity({'id': 'personal', 'name': 'personal'})
        full = Accounting(other)
        actual = self.app.start('home', 'personal', T, 'start')
        expected = full.start('home', 'personal', T, 'start')
        for index in range(720):
            left = T + timedelta(seconds=index * 5)
            right = left + timedelta(seconds=5)
            energy = D('0') if index % 2 else D('.002')
            prices = [(left, D('-1') if index % 3 else D('2'))]
            self.app.add_interval('home', left, right, energy, prices)
            data = full._interval_data('home', left, right, energy, prices, ())
            with other.transaction():
                other.put_interval(data)
                rebuilt, parts, _ = full._build(other.get_record(expected['id']))
                rebuilt['revision'] += 1
                other.save_record(rebuilt, parts, audit=False)
        result = self.ledger.get_record(actual['id'])
        self.assertEqual(D(result['energy_kwh']), D('.720'))
        self.assertEqual(D(result['known_cost']), D('0'))
        self.assertEqual({**result, 'id': expected['id']}, other.get_record(expected['id']))
        self.assertEqual(self.ledger.list_segments(actual['id']), other.list_segments(expected['id']))
        self.assertEqual(result['_segment_count'], 720)

    def test_append_failure_rolls_back_observation_cursor_and_retry(self):
        record = self.app.start('home', 'personal', T, 'start')
        self.interval()
        before = self.ledger.get_record(record['id'])
        version = self.ledger.data_version()
        self.ledger._db.execute("CREATE TEMP TRIGGER fail_append BEFORE INSERT ON segments WHEN NEW.position=1 BEGIN SELECT RAISE(ABORT, 'append failed'); END")
        with self.assertRaisesRegex(Exception, 'append failed'):
            self.interval(T + timedelta(seconds=30), T + timedelta(seconds=35), '.001')
        self.assertEqual(self.ledger.get_record(record['id']), before)
        self.assertEqual(self.ledger.data_version(), version)
        self.assertEqual(len(self.ledger.list_intervals('home')), 1)
        self.assertEqual(len(self.ledger.list_segments(record['id'])), 1)
        self.ledger._db.execute('DROP TRIGGER fail_append')
        for _ in range(2):
            self.interval(T + timedelta(seconds=30), T + timedelta(seconds=35), '.001')
        self.assertEqual(D(self.ledger.get_record(record['id'])['energy_kwh']), D('.061'))
        self.assertEqual(self.ledger.get_record(record['id'])['_segment_count'], 2)

    def test_append_precision_midnight_price_changes_and_unknown_cost(self):
        start = T - timedelta(seconds=7)
        record = self.app.start('home', 'personal', start, 'start', timezone='UTC')
        samples = [
            (start, T - timedelta(seconds=2), '123456789.123456789123456789123456789', [(start, D('1.23456789123456789123456789'))]),
            (T - timedelta(seconds=2), T + timedelta(seconds=3), '.000000000000000000000001234567891',
             [(T - timedelta(seconds=2), D('-.123456789123456789123456789')), (T + timedelta(seconds=1), D('2'))]),
            (T + timedelta(seconds=3), T + timedelta(seconds=8), '.002', []),
            (T + timedelta(seconds=8), T + timedelta(seconds=13), '.003', [(T + timedelta(seconds=8), D('1'))]),
        ]
        for left, right, energy, prices in samples:
            self.app.add_interval('home', left, right, D(energy), prices)
            actual = self.ledger.get_record(record['id'])
            expected, parts, _ = self.app._build(dict(actual))
            self.assertEqual(actual, expected)
            self.assertEqual(self.ledger.list_segments(record['id']), parts)
        self.assertFalse(actual['cost_complete'])
        self.assertEqual(actual['quality'], ['estimated', 'missing_price', 'provisional'])
        self.assertEqual(actual['_segment_count'], 6)

    def test_restart_continues_append_from_persisted_cursor(self):
        record = self.app.start('home', 'personal', T, 'start')
        self.interval()
        reopened = Ledger(str(Path(self.directory.name) / 'db'))
        self.addCleanup(reopened.close)
        sql = []
        reopened._db.set_trace_callback(sql.append)
        Accounting(reopened).add_interval('home', T + timedelta(seconds=30), T + timedelta(seconds=35),
                                         D('.001'), [(T + timedelta(seconds=30), D('1'))])
        self.assertFalse(any('DELETE FROM segments' in statement for statement in sql))
        self.assertEqual(D(reopened.get_record(record['id'])['energy_kwh']), D('.061'))
        self.assertEqual(reopened.get_record(record['id'])['_segment_count'], 2)

    def test_partial_start_gap_reset_and_late_samples_use_rebuild(self):
        record = self.app.start('home', 'personal', T + timedelta(seconds=10), 'start')
        for left, right, quality in [(0, 30, ()), (30, 40, ('reset',)), (50, 60, ())]:
            sql = []
            self.ledger._db.set_trace_callback(sql.append)
            self.app.add_interval('home', T + timedelta(seconds=left), T + timedelta(seconds=right),
                                  D('.030'), [(T, D('1'))], quality)
            self.ledger._db.set_trace_callback(None)
            self.assertTrue(any('DELETE FROM segments' in statement for statement in sql))
        current = self.ledger.get_record(record['id'])
        self.assertEqual(D(current['energy_kwh']), D('.050'))
        self.assertIn('missing_energy', current['quality'])
        self.app.end(record['id'], T + timedelta(seconds=70), 'end')
        self.interval(T + timedelta(seconds=60), T + timedelta(seconds=70), '.001')
        current = self.ledger.get_record(record['id'])
        self.assertEqual(D(current['energy_kwh']), D('.051'))
        self.assertEqual(self.ledger.list_revisions(record['id'])[-1]['record'], current)

    def test_append_rejects_stale_segment_count_without_changing_ledger(self):
        record = self.app.start('home', 'personal', T, 'start')
        self.interval()
        before = self.ledger.get_record(record['id'])
        version = self.ledger.data_version()
        with self.assertRaisesRegex(ValueError, 'count conflict'):
            self.ledger.append_record_segments({**before, 'revision': before['revision'] + 1}, [], 0)
        self.assertEqual(self.ledger.get_record(record['id']), before)
        self.assertEqual(self.ledger.data_version(), version)
        self.assertEqual(len(self.ledger.list_segments(record['id'])), 1)

    def test_live_samples_update_revision_without_audit_snapshots(self):
        record = self.app.start('home', 'personal', T, 'start')
        version = self.ledger.data_version()
        self.interval()
        current = self.ledger.get_record(record['id'])
        self.assertGreater(current['revision'], record['revision'])
        self.assertGreater(self.ledger.data_version(), version)
        self.assertEqual(len(self.ledger.list_revisions(record['id'])), 1)
        with self.assertRaisesRegex(ValueError, 'revision'):
            self.app.reassign(record['id'], 'company', record['revision'])
        self.app.end(record['id'], T + timedelta(seconds=30), 'end')
        self.assertEqual([r['record']['revision'] for r in self.ledger.list_revisions(record['id'])], [1, 3])

    def test_batch_refresh_nested_rollback_and_no_change(self):
        record = self.app.start('home', 'personal', T, 'start')
        self.app.end(record['id'], T + timedelta(seconds=90), 'end')
        with self.app.batch_refresh():
            self.interval()
            with self.assertRaisesRegex(ValueError, 'abort'):
                with self.app.batch_refresh():
                    self.interval(T + timedelta(seconds=30), T + timedelta(seconds=60))
                    raise ValueError('abort')
            with self.app.batch_refresh():
                self.interval(T + timedelta(seconds=60), T + timedelta(seconds=90))
        current = self.ledger.get_record(record['id'])
        self.assertEqual(D(current['energy_kwh']), D('.120'))
        self.assertEqual(current['revision'], 3)
        self.assertEqual(len(self.ledger.list_revisions(record['id'])), 3)
        version = self.ledger.data_version()
        with self.app.batch_refresh():
            self.app._refresh('home', T.isoformat(), (T + timedelta(seconds=90)).isoformat())
        self.assertEqual(self.ledger.data_version(), version)
        with self.assertRaisesRegex(ValueError, 'abort'):
            with self.app.batch_refresh():
                self.interval(T + timedelta(seconds=30), T + timedelta(seconds=60))
                raise ValueError('abort')
        self.assertEqual(self.ledger.get_record(record['id']), current)
        self.interval(T + timedelta(seconds=30), T + timedelta(seconds=60))
        self.assertEqual(D(self.ledger.get_record(record['id'])['energy_kwh']), D('.180'))

    def test_batch_audit_failure_rolls_back_current_data_and_observations(self):
        record = self.app.start('home', 'personal', T, 'start')
        ended = self.app.end(record['id'], T + timedelta(seconds=30), 'end')
        revisions = self.ledger.list_revisions(record['id'])
        version = self.ledger.data_version()

        def fail(record_id):
            self.assertEqual(D(self.ledger.get_record(record_id)['known_cost']), D('.060'))
            self.assertEqual(len(self.ledger.list_segments(record_id)), 1)
            raise OSError('audit failure')

        with patch.object(self.ledger, 'save_revision', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'audit failure'):
                with self.app.batch_refresh():
                    self.interval()
        self.assertEqual(self.ledger.get_record(record['id']), ended)
        self.assertEqual(self.ledger.list_segments(record['id']), [])
        self.assertEqual(self.ledger.list_intervals('home'), [])
        self.assertEqual(self.ledger.list_revisions(record['id']), revisions)
        self.assertEqual(self.ledger.data_version(), version)
        self.interval()
        self.assertEqual(len(self.ledger.list_revisions(record['id'])), 3)

    def test_prune_keeps_current_segments_without_an_audit_snapshot(self):
        record = self.app.start('home', 'personal', T, 'start')
        self.interval()
        self.assertEqual(self.ledger.list_revisions(record['id'])[0]['segments'], [])
        self.ledger.prune(before=T + timedelta(days=365))
        self.assertEqual(len(self.ledger.list_intervals('home')), 1)
        self.assertEqual(len(self.ledger.list_segments(record['id'])), 1)

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
        original_segments = self.ledger.list_segments(record['id'])
        self.assertEqual(original_segments[0]['unit_price'], '1')
        self.assertEqual(original_segments[0]['cost_basis'], 'tariff')
        self.ledger.put_price_version({'id': 'new', 'point_id': 'home', 'at': T.isoformat(), 'price': '2'})
        edit = self.app.preview({'record_id': record['id'], 'expected_revision': record['revision'],
                                 'identity_id': 'company', 'note': 'corrected'})
        changed = self.app.commit_preview(edit['token'], 'edit')
        self.assertEqual(changed['known_cost'], record['known_cost'])
        self.assertEqual(changed['note'], 'corrected')
        self.assertEqual(self.ledger.list_segments(record['id']), original_segments)

    def test_manual_cost_metadata_for_explicit_energy_and_measured_gaps(self):
        self.interval(end=T + timedelta(seconds=10))
        for measured in (False, True):
            for cost in ('5', None):
                with self.subTest(measured=measured, cost=cost):
                    data = self.manual(end=T + timedelta(seconds=30), cost=cost)
                    if measured:
                        del data['energy_kwh']
                    preview = self.app.preview(data)
                    self.assertTrue(preview['segments'])
                    for part in preview['segments']:
                        self.assertIsNone(part['unit_price'])
                        self.assertEqual(part['cost_basis'], 'unknown' if cost is None else 'manual')
                    if measured:
                        self.assertEqual(len(preview['segments']), 2)
                        self.assertEqual(D(preview['segments'][1]['energy_kwh']), 0)

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

    def test_adjacent_observed_prices_override_synthetic_end_boundaries(self):
        for second_price, expected, complete in [('2', '6', True), ('4', '10', True), (None, '2', False)]:
            with self.subTest(second_price=second_price):
                point_id = 'adjacent-' + str(second_price)
                self.ledger.put_point({'id': point_id, 'name': point_id})
                boundary = T + timedelta(seconds=10)
                end = T + timedelta(seconds=30)
                self.app.add_interval(point_id, T, boundary, D('1'), [(T, D('2'))])
                self.app.add_interval(point_id, boundary, end, D('2'), [(boundary, None if second_price is None else D(second_price))])
                data = self.manual(point_id=point_id, end=end, energy_kwh='3')
                del data['cost']
                preview = self.app.preview(data)
                self.assertEqual(D(preview['record']['known_cost']), D(expected))
                self.assertEqual(preview['record']['cost_complete'], complete)
                if second_price is None:
                    self.assertIsNone(preview['segments'][-1]['cost'])

    def test_observed_price_anchor_restores_after_uncovered_gap(self):
        self.app.add_interval('home', T, T + timedelta(seconds=10), D(1), [(T, D(2))])
        self.app.add_interval('home', T + timedelta(seconds=20), T + timedelta(seconds=30), D(1), [(T, D(2))])
        data = self.manual(end=T + timedelta(seconds=30), energy_kwh='3')
        del data['cost']
        preview = self.app.preview(data)
        self.assertEqual([None if s['cost'] is None else D(s['cost']) for s in preview['segments']], [D(2), None, D(2)])
        self.assertEqual(D(preview['record']['known_cost']), 4)
        self.assertFalse(preview['record']['cost_complete'])

    def test_empty_price_observation_does_not_restore_pruned_price(self):
        for day in (0, 1, 2):
            self.ledger.put_price_version({'id': str(day), 'point_id': 'home',
                                          'at': (T + timedelta(days=day)).isoformat(), 'price': str(day + 1)})
        kept = self.manual(end=T + timedelta(seconds=30), energy_kwh='1')
        del kept['cost']
        self.app.commit_preview(self.app.preview(kept)['token'], 'kept')
        self.ledger.prune(T + timedelta(days=200))
        self.assertEqual([p['id'] for p in self.ledger.list_price_versions('home')], ['0', '2'])
        left = T + timedelta(days=1, hours=1)
        self.app.add_interval('home', left, left + timedelta(seconds=10), D(1), [])
        data = self.manual(start=left, end=left + timedelta(seconds=10), energy_kwh='1')
        del data['cost']
        preview = self.app.preview(data)
        self.assertFalse(preview['record']['cost_complete'])
        self.assertIsNone(preview['segments'][0]['cost'])

        restored = left + timedelta(seconds=10)
        self.app.add_interval('home', restored, restored + timedelta(seconds=10), D(1), [(restored, D(4))])
        data.update(start=restored, end=restored + timedelta(seconds=10))
        preview = self.app.preview(data)
        self.assertTrue(preview['record']['cost_complete'])
        self.assertEqual(D(preview['record']['known_cost']), 4)

        unavailable = restored + timedelta(seconds=10)
        self.app.add_interval('home', unavailable, unavailable + timedelta(seconds=10), D(1), [(unavailable, None)])
        data.update(start=unavailable, end=unavailable + timedelta(seconds=10))
        preview = self.app.preview(data)
        self.assertFalse(preview['record']['cost_complete'])
        self.assertIsNone(preview['segments'][0]['cost'])

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
