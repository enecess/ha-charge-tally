"""A process exiting before COMMIT cannot partially change accounting data."""

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from custom_components.charge_tally.accounting import Accounting
from custom_components.charge_tally.ledger import Ledger, retained_currency

ROOT = Path(__file__).parents[2]
CHILD = """
import os
import sys
from custom_components.charge_tally.ledger import Ledger
ledger = Ledger(sys.argv[1])
record = dict(ledger.get_record('record'), revision=2, energy_kwh='2')
with ledger.transaction():
    ledger.save_record(record, [{'energy_kwh': '2', 'cost': '1', 'unit_price': '0.5', 'cost_basis': 'tariff'}])
    ledger.put_checkpoint('cursor', {'sequence': 2})
    os._exit(23)
"""


class ProcessRecoveryTests(unittest.TestCase):
    def test_uncommitted_append_recovers_cursor_and_retries_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "ledger.sqlite3")
            at = datetime(2026, 1, 1, tzinfo=UTC)
            ledger = Ledger(path)
            ledger.put_point({"id": "p", "name": "Point"})
            ledger.put_identity({"id": "i", "name": "Identity"})
            app = Accounting(ledger)
            record = app.start("p", "i", at, "start")
            app.add_interval(
                "p",
                at,
                at + timedelta(seconds=5),
                Decimal(".001"),
                [(at, Decimal("1"))],
            )
            before = ledger.get_record(record["id"])
            version = ledger.data_version()
            ledger.close()
            child = """
import os, sys
from datetime import datetime, timedelta
from decimal import Decimal
from custom_components.charge_tally.ledger import Ledger
from custom_components.charge_tally.accounting import Accounting
ledger = Ledger(sys.argv[1])
at = datetime.fromisoformat('2026-01-01T00:00:05+00:00')
with ledger.transaction():
    Accounting(ledger).add_interval('p', at, at + timedelta(seconds=5), Decimal('.002'), [(at, Decimal('1'))])
    os._exit(23)
"""
            process = subprocess.run(
                [sys.executable, "-c", child, path], cwd=ROOT, check=False
            )
            self.assertEqual(process.returncode, 23)
            with closing(Ledger(path)) as restored:
                self.assertEqual(restored.get_record(record["id"]), before)
                self.assertEqual(restored.data_version(), version)
                self.assertEqual(len(restored.list_segments(record["id"])), 1)
                self.assertEqual(len(restored.list_intervals("p")), 1)
                app = Accounting(restored)
                for _ in range(2):
                    app.add_interval(
                        "p",
                        at + timedelta(seconds=5),
                        at + timedelta(seconds=10),
                        Decimal(".002"),
                        [(at + timedelta(seconds=5), Decimal("1"))],
                    )
                current = restored.get_record(record["id"])
                self.assertEqual(current["_segment_count"], 2)
                self.assertEqual(
                    current["_accounted_until"], "2026-01-01T00:00:10+00:00"
                )
                self.assertEqual(Decimal(current["energy_kwh"]), Decimal(".003"))

    def test_sparse_revisions_survive_reopen_and_continue_monotonically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "ledger.sqlite3")
            at = datetime(2026, 1, 1, tzinfo=UTC)
            ledger = Ledger(path)
            ledger.put_point({"id": "p", "name": "Point"})
            ledger.put_identity({"id": "i", "name": "Identity"})
            app = Accounting(ledger)
            record = app.start("p", "i", at, "start")
            for index in range(3):
                left = at + timedelta(seconds=30 * index)
                app.add_interval(
                    "p",
                    left,
                    left + timedelta(seconds=30),
                    Decimal("1"),
                    [(left, Decimal("2"))],
                )
            version = ledger.data_version()
            ledger.close()
            with closing(Ledger(path)) as ledger:
                self.assertEqual(ledger.get_record(record["id"])["revision"], 4)
                self.assertEqual(
                    [
                        r["record"]["revision"]
                        for r in ledger.list_revisions(record["id"])
                    ],
                    [1],
                )
                self.assertEqual(ledger.data_version(), version)
                ended = Accounting(ledger).end(
                    record["id"], at + timedelta(seconds=90), "end"
                )
                self.assertEqual(ended["revision"], 5)
                self.assertGreater(ledger.data_version(), version)
                revisions = ledger.list_revisions(record["id"])
                self.assertEqual([r["record"]["revision"] for r in revisions], [1, 5])
                self.assertEqual(revisions[0]["record"]["energy_kwh"], "0")
                self.assertEqual(revisions[-1]["record"]["energy_kwh"], "3")

    def test_unknown_schema_is_rejected_without_modifying_the_database(self):
        for version in (0, 1, 99):
            with (
                self.subTest(version=version),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "unsupported.sqlite3"
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute(f"PRAGMA user_version={version}")
                    db.execute("CREATE TABLE old_data (value TEXT)")
                    db.execute("INSERT INTO old_data VALUES ('preserved')")
                before = path.read_bytes()
                for reader in (Ledger, retained_currency):
                    with self.assertRaisesRegex(
                        ValueError, "Unsupported ledger schema"
                    ):
                        result = reader(str(path))
                        if isinstance(result, Ledger):
                            result.close()
                    self.assertEqual(path.read_bytes(), before)

    def test_empty_database_can_be_initialized_and_reopened(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.sqlite3"
            with closing(sqlite3.connect(path)):
                pass
            self.assertIsNone(retained_currency(path))
            ledger = Ledger(str(path))
            ledger.bind_currency("CNY")
            ledger.close()
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (2,))
            self.assertEqual(retained_currency(path), "CNY")
            ledger = Ledger(str(path))
            self.assertEqual(ledger.currency, "CNY")
            ledger.close()

    def test_interrupted_transaction_then_commit_and_snapshot_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            ledger = Ledger(str(path))
            ledger.put_identity({"id": "identity", "name": "Car"})
            ledger.put_point({"id": "point", "name": "Garage"})
            record = {
                "id": "record",
                "point_id": "point",
                "identity_id": "identity",
                "start": "2026-01-01T00:00:00+00:00",
                "end": "2026-01-01T01:00:00+00:00",
                "status": "ended",
                "revision": 1,
                "energy_kwh": "1",
            }
            with ledger.transaction():
                ledger.save_record(
                    record,
                    [
                        {
                            "energy_kwh": "1",
                            "cost": "0.5",
                            "unit_price": "0.5",
                            "cost_basis": "tariff",
                        }
                    ],
                )
                ledger.put_checkpoint("cursor", {"sequence": 1})
            original_revisions = ledger.list_revisions("record")
            ledger.close()
            child = subprocess.run(
                [sys.executable, "-c", CHILD, str(path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(child.returncode, 23, child.stdout + child.stderr)
            ledger = Ledger(str(path))
            try:
                self.assertEqual(ledger.get_record("record"), record)
                self.assertEqual(
                    ledger.list_segments("record"),
                    [
                        {
                            "energy_kwh": "1",
                            "cost": "0.5",
                            "unit_price": "0.5",
                            "cost_basis": "tariff",
                        }
                    ],
                )
                self.assertEqual(ledger.list_revisions("record"), original_revisions)
                self.assertEqual(ledger.get_checkpoint("cursor"), {"sequence": 1})
                with ledger.transaction():
                    ledger.save_record(
                        dict(record, revision=2, energy_kwh="2"),
                        [
                            {
                                "energy_kwh": "2",
                                "cost": "1",
                                "unit_price": "0.5",
                                "cost_basis": "tariff",
                            }
                        ],
                    )
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
                    self.assertEqual(
                        restored.list_segments("record"),
                        [
                            {
                                "energy_kwh": "2",
                                "cost": "1",
                                "unit_price": "0.5",
                                "cost_basis": "tariff",
                            }
                        ],
                    )
                    self.assertEqual(len(restored.list_revisions("record")), 2)
                    self.assertEqual(restored.get_checkpoint("cursor"), {"sequence": 2})
                finally:
                    restored.close()
                with closing(
                    sqlite3.connect(restored_path.as_uri() + "?mode=ro", uri=True)
                ) as db:
                    self.assertEqual(
                        db.execute("PRAGMA integrity_check").fetchone(), ("ok",)
                    )
