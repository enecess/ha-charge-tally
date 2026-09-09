"""Real SQLite persistence and transaction tests."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from custom_components.charge_tally.ledger import Ledger


class LedgerTests(unittest.TestCase):
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
