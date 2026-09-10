"""A process exiting before COMMIT cannot partially change accounting data."""
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from custom_components.charge_tally.ledger import Ledger


ROOT = Path(__file__).parents[2]
CHILD = """
import os
import sys
from custom_components.charge_tally.ledger import Ledger
ledger = Ledger(sys.argv[1])
record = dict(ledger.get_record('record'), revision=2, energy_kwh='2')
with ledger.transaction():
    ledger.save_record(record, [{'energy_kwh': '2', 'cost': '1'}])
    ledger.put_checkpoint('cursor', {'sequence': 2})
    os._exit(23)
"""


class ProcessRecoveryTests(unittest.TestCase):
    def test_unknown_schema_is_rejected_without_modifying_the_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "future.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("PRAGMA user_version=99")
                db.execute("CREATE TABLE future_data (value TEXT)")
                db.execute("INSERT INTO future_data VALUES ('preserved')")
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "Unsupported ledger schema"):
                Ledger(str(path))
            self.assertEqual(path.read_bytes(), before)

    def test_interrupted_transaction_then_commit_and_snapshot_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            ledger = Ledger(str(path))
            ledger.put_identity({"id": "identity", "name": "Car"})
            ledger.put_point({"id": "point", "name": "Garage"})
            record = {"id": "record", "point_id": "point", "identity_id": "identity",
                      "start": "2026-01-01T00:00:00+00:00", "end": "2026-01-01T01:00:00+00:00",
                      "status": "ended", "revision": 1, "energy_kwh": "1"}
            with ledger.transaction():
                ledger.save_record(record, [{"energy_kwh": "1", "cost": "0.5"}])
                ledger.put_checkpoint("cursor", {"sequence": 1})
            original_revisions = ledger.list_revisions("record")
            ledger.close()
            child = subprocess.run([sys.executable, "-c", CHILD, str(path)], cwd=ROOT,
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(child.returncode, 23, child.stdout + child.stderr)
            ledger = Ledger(str(path))
            try:
                self.assertEqual(ledger.get_record("record"), record)
                self.assertEqual(ledger.list_segments("record"), [{"energy_kwh": "1", "cost": "0.5"}])
                self.assertEqual(ledger.list_revisions("record"), original_revisions)
                self.assertEqual(ledger.get_checkpoint("cursor"), {"sequence": 1})
                with ledger.transaction():
                    ledger.save_record(dict(record, revision=2, energy_kwh="2"), [{"energy_kwh": "2", "cost": "1"}])
                    ledger.put_checkpoint("cursor", {"sequence": 2})
                snapshot = Path(directory) / "snapshot.sqlite3"
                ledger.backup(str(snapshot))
            finally:
                ledger.close()
            for restored_path in (path, snapshot):
                restored = Ledger(str(restored_path))
                try:
                    self.assertEqual(restored.get_record("record")["energy_kwh"], "2")
                    self.assertEqual(restored.get_record("record")["revision"], 2)
                    self.assertEqual(restored.list_segments("record"), [{"energy_kwh": "2", "cost": "1"}])
                    self.assertEqual(len(restored.list_revisions("record")), 2)
                    self.assertEqual(restored.get_checkpoint("cursor"), {"sequence": 2})
                finally:
                    restored.close()
                with sqlite3.connect(restored_path.as_uri() + "?mode=ro", uri=True) as db:
                    self.assertEqual(db.execute("PRAGMA integrity_check").fetchone(), ("ok",))
