"""Real SQLite persistence and transaction tests."""
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from custom_components.charge_tally.ledger import Ledger


class LedgerTests(unittest.TestCase):
    def test_currency_change_only_before_accounting_use(self):
        with tempfile.TemporaryDirectory() as directory, closing(Ledger(str(Path(directory) / 'ledger.db'))) as ledger:
            ledger.bind_currency('CNY')
            ledger.put_identity({'id': 'car', 'name': 'Car'})
            self.assertTrue(ledger.currency_change_allowed())
            ledger.change_currency('USD', 'CNY')
            self.assertEqual(ledger.currency, 'USD')
            self.assertEqual(ledger.get_identity('car')['name'], 'Car')
            with self.assertRaisesRegex(ValueError, 'config_changed'):
                ledger.change_currency('EUR', 'CNY')
            with self.assertRaisesRegex(ValueError, 'invalid_currency'):
                ledger.change_currency('bad unit', 'USD')
            ledger.put_point({'id': 'old', 'name': 'Old', 'active': False})
            self.assertFalse(ledger.currency_change_allowed())
            with self.assertRaisesRegex(ValueError, 'currency_locked'):
                ledger.change_currency('EUR', 'USD')
            self.assertEqual(ledger.currency, 'USD')
            ledger.close()

    def test_roundtrip_rollback_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'ledger.db')
            ledger = Ledger(path)
            ledger.put_identity({'id': 'personal', 'name': 'Personal'})
            ledger.put_point({'id': 'home', 'name': 'Home'})
            with self.assertRaises(ValueError):
                with ledger.transaction():
                    ledger.put_checkpoint('home', {'cursor': 3})
                    ledger.put_identity({'id': 'temporary', 'name': 'Temporary'})
                    raise ValueError('Injected application failure')
            self.assertIsNone(ledger.get_checkpoint('home'))
            self.assertIsNone(ledger.get_identity('temporary'))
            ledger.put_checkpoint('home', {'cursor': 4})
            ledger.put_price_version({'id': 'price1', 'point_id': 'home', 'at': '2026-01-01T00:00:00+00:00', 'price': '-1'})
            backup = str(Path(directory) / 'backup.db')
            ledger.backup(backup)
            ledger.close()
            for filename in (path, backup):
                restored = Ledger(filename)
                self.assertEqual(restored.get_checkpoint('home'), {'cursor': 4})
                self.assertEqual(restored.list_identities()[0]['name'], 'Personal')
                self.assertEqual(restored.list_points()[0]['name'], 'Home')
                self.assertEqual(restored.list_price_versions('home')[0]['price'], '-1')
                restored.close()

    def test_prune_old_unreferenced_prices_keeps_effective_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(str(Path(directory) / 'ledger.db'))
            try:
                ledger.put_point({'id': 'home', 'name': 'Home'})
                for index, date in enumerate(('2025-01-01', '2025-02-01', '2026-08-01')):
                    ledger.put_price_version({'id': str(index), 'point_id': 'home', 'at': date + 'T00:00:00+00:00', 'price': str(index)})
                self.assertEqual(ledger.prune(datetime(2026, 1, 1, tzinfo=timezone.utc)), 1)
                self.assertEqual([p['id'] for p in ledger.list_price_versions('home')], ['1', '2'])
            finally:
                ledger.close()

    def test_archived_identity_name_can_be_reused_without_reassigning_history(self):
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        ledger.put_identity({'id': 'old', 'name': 'Personal', 'active': False})
        ledger.put_identity({'id': 'new', 'name': 'Personal'})
        self.assertFalse(ledger.get_identity('old')['active'])
        self.assertEqual(ledger.get_identity('new')['name'], 'Personal')
        with self.assertRaises(ValueError):
            ledger.put_identity({'id': 'third', 'name': 'Personal'})
        with self.assertRaises(ValueError):
            ledger.put_identity({'id': 'old', 'name': 'Personal', 'active': True})

    def test_price_prune_protects_actual_record_range_and_anchor_only(self):
        from custom_components.charge_tally.accounting import Accounting
        ledger = Ledger(':memory:')
        self.addCleanup(ledger.close)
        ledger.put_identity({'id': 'personal', 'name': 'Personal'})
        ledger.put_point({'id': 'home', 'name': 'Home'})
        for day in (1, 2, 3):
            ledger.put_price_version({'id': str(day), 'point_id': 'home', 'at': f'2026-01-0{day}T00:00:00+00:00', 'price': str(day)})
        app = Accounting(ledger)
        preview = app.preview({'point_id': 'home', 'identity_id': 'personal', 'start': '2026-01-01T00:00:00+00:00',
                               'end': '2026-01-01T01:00:00+00:00', 'energy_kwh': '1'})
        app.commit_preview(preview['token'], 'save')
        self.assertEqual(ledger.prune(datetime(2026, 8, 1, tzinfo=timezone.utc)), 1)
        self.assertEqual([p['id'] for p in ledger.list_price_versions('home')], ['1', '3'])
        missing = app.preview({'point_id': 'home', 'identity_id': 'personal', 'start': '2026-01-02T00:00:00+00:00',
                               'end': '2026-01-02T01:00:00+00:00', 'energy_kwh': '1'})
        self.assertFalse(missing['record']['cost_complete'])
        self.assertIsNone(missing['segments'][0]['cost'])
