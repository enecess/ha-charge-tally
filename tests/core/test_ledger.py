"""Real SQLite persistence and transaction tests."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from custom_components.charge_tally.ledger import Ledger


class LedgerTests(unittest.TestCase):
    def test_prune_batches_audit_observation_references_with_idle_candidates(self):
        from datetime import timedelta

        with closing(Ledger(":memory:")) as ledger:
            ledger.put_point({"id": "p"})
            ledger.put_identity({"id": "i", "name": "Car"})
            start = datetime(2025, 1, 1, tzinfo=UTC)
            for index in range(302):
                left = start + timedelta(seconds=index)
                ledger.put_interval(
                    dict(
                        id=str(index),
                        point_id="p",
                        start=left.isoformat(),
                        end=(left + timedelta(seconds=1)).isoformat(),
                        gap=index == 0,
                    )
                )
            record = dict(
                id="r",
                point_id="p",
                identity_id="i",
                status="ended",
                revision=1,
                start=(start + timedelta(days=2)).isoformat(),
                end=(start + timedelta(days=3)).isoformat(),
            )
            ledger.save_record(record, [{"observation_id": "1"}] * 2000)
            ledger.save_record({**record, "revision": 2}, [])
            history = ledger.list_revisions("r")
            statements = []
            work = []
            ledger._db.set_trace_callback(statements.append)
            ledger._db.set_progress_handler(lambda: work.append(1) or 0, 1000)
            cutoff = datetime(2026, 1, 1, tzinfo=UTC)
            self.assertEqual(ledger.prune(cutoff, limit=300), 298)
            ledger._db.set_trace_callback(None)
            ledger._db.set_progress_handler(None, 0)
            self.assertEqual(
                ledger.get_checkpoint("_prune_progress")["after"][1], "299"
            )
            self.assertIsNotNone(ledger._get("observations", "300"))
            self.assertEqual(ledger.list_revisions("r"), history)
            self.assertIsNotNone(ledger._get("observations", "1"))
            audit_queries = [sql for sql in statements if "FROM revisions" in sql]
            self.assertLessEqual(len(audit_queries), 1, len(audit_queries))
            self.assertLess(
                len(work), 1000, "Repeated historical scans amplify SQLite work"
            )
            self.assertEqual(ledger.prune(cutoff, limit=300), 2)
            self.assertFalse(ledger.prune_pending())
            self.assertEqual(
                [row["id"] for row in ledger.list_intervals("p")], ["0", "1"]
            )

    def test_prune_batches_audit_price_ranges_with_idle_candidates(self):
        from datetime import timedelta

        with closing(Ledger(":memory:")) as ledger:
            ledger.put_point({"id": "p"})
            ledger.put_identity({"id": "i", "name": "Car"})
            start = datetime(2022, 1, 1, tzinfo=UTC)
            for index in range(302):
                ledger.put_price_version(
                    dict(
                        id=str(index),
                        point_id="p",
                        price="0.5",
                        at=(start + timedelta(seconds=index)).isoformat(),
                    )
                )
            record = dict(
                id="r",
                point_id="p",
                identity_id="i",
                status="ended",
                revision=1,
                start=(start + timedelta(seconds=1)).isoformat(),
                end=(start + timedelta(seconds=2)).isoformat(),
            )
            ledger.save_record(record, [])
            for index in range(1001):
                left = start + timedelta(days=2, hours=8 * index)
                ledger.save_record(
                    {
                        **record,
                        "id": f"past-{index}",
                        "start": left.isoformat(),
                        "end": (left + timedelta(hours=1)).isoformat(),
                    },
                    [],
                )
            history = ledger._db.execute(
                "SELECT data FROM revisions ORDER BY record_id,revision"
            ).fetchall()
            statements = []
            work = []
            ledger._db.set_trace_callback(statements.append)
            ledger._db.set_progress_handler(lambda: work.append(1) or 0, 1000)
            cutoff = datetime(2026, 1, 1, tzinfo=UTC)
            self.assertEqual(ledger.prune(cutoff, limit=300), 299)
            ledger._db.set_trace_callback(None)
            ledger._db.set_progress_handler(None, 0)
            self.assertEqual(
                ledger.get_checkpoint("_prune_progress")["after"][1], "299"
            )
            self.assertEqual(
                ledger._db.execute(
                    "SELECT data FROM revisions ORDER BY record_id,revision"
                ).fetchall(),
                history,
            )
            self.assertIsNotNone(ledger._get("price_versions", "1"))
            self.assertIsNotNone(ledger._get("price_versions", "300"))
            audit_queries = [sql for sql in statements if "FROM revisions" in sql]
            self.assertLessEqual(len(audit_queries), 1, len(audit_queries))
            self.assertLess(
                len(work), 1000, "Repeated historical scans amplify SQLite work"
            )
            self.assertEqual(ledger.prune(cutoff, limit=300), 1)
            self.assertFalse(ledger.prune_pending())
            self.assertEqual(
                [row["id"] for row in ledger.list_price_versions("p")], ["1", "301"]
            )
            self.assertEqual(
                ledger.get_checkpoint("_price_gaps:p"),
                [
                    {
                        "start": start.isoformat(),
                        "end": (start + timedelta(seconds=1)).isoformat(),
                    },
                    {
                        "start": (start + timedelta(seconds=2)).isoformat(),
                        "end": (start + timedelta(seconds=301)).isoformat(),
                    },
                ],
            )

    def test_price_prune_preserves_tied_successors_across_candidate_batches(self):
        from datetime import timedelta

        with closing(Ledger(":memory:")) as ledger:
            ledger.put_point({"id": "p"})
            ledger.put_identity({"id": "i", "name": "Car"})
            start = datetime(2022, 1, 1, tzinfo=UTC)
            for id_, second in (
                ("old", 0),
                ("tie-a", 1),
                ("tie-b", 1),
                ("next", 2),
                ("anchor", 3),
            ):
                ledger.put_price_version(
                    {
                        "id": id_,
                        "point_id": "p",
                        "price": "0.5",
                        "at": (start + timedelta(seconds=second)).isoformat(),
                    }
                )
            ledger.save_record(
                {
                    "id": "r",
                    "point_id": "p",
                    "identity_id": "i",
                    "revision": 1,
                    "status": "ended",
                    "start": (start + timedelta(seconds=1)).isoformat(),
                    "end": (start + timedelta(seconds=2)).isoformat(),
                },
                [],
            )
            history = ledger.list_revisions("r")
            cutoff = datetime(2026, 1, 1, tzinfo=UTC)
            self.assertEqual(ledger.prune(cutoff, limit=2), 2)
            self.assertEqual(
                ledger.get_checkpoint("_prune_progress"),
                {
                    "phase": "price_versions",
                    "cutoff": cutoff.isoformat(),
                    "after": [(start + timedelta(seconds=1)).isoformat(), "tie-a"],
                },
            )
            self.assertIsNotNone(ledger._get("price_versions", "tie-b"))
            self.assertEqual(ledger.prune(cutoff, limit=2), 1)
            self.assertEqual(ledger.prune(cutoff, limit=2), 0)
            self.assertFalse(ledger.prune_pending())
            self.assertEqual(
                [row["id"] for row in ledger.list_price_versions("p")],
                ["tie-b", "anchor"],
            )
            self.assertEqual(ledger.list_revisions("r"), history)
            self.assertEqual(
                ledger.get_checkpoint("_price_gaps:p"),
                [
                    {
                        "start": start.isoformat(),
                        "end": (start + timedelta(seconds=1)).isoformat(),
                    },
                    {
                        "start": (start + timedelta(seconds=2)).isoformat(),
                        "end": (start + timedelta(seconds=3)).isoformat(),
                    },
                ],
            )

    def test_narrow_queries_decode_only_matching_ordered_evidence(self):
        import json

        with closing(Ledger(":memory:")) as ledger:
            for point in ("p", "other"):
                ledger.put_point({"id": point})
                for id_, at in (("z", "01"), ("a", "02"), ("b", "02"), ("c", "03")):
                    ledger.put_price_version(
                        {
                            "id": point + id_,
                            "point_id": point,
                            "at": f"2026-01-0{at[-1]}T00:00:00+00:00",
                            "price": id_,
                        }
                    )
                for day in (1, 2, 3):
                    ledger.put_interval(
                        {
                            "id": point + str(day),
                            "point_id": point,
                            "start": f"2026-01-0{day}T00:00:00+00:00",
                            "end": f"2026-01-0{day}T01:00:00+00:00",
                        }
                    )
            start, end = "2026-01-02T00:30:00+00:00", "2026-01-03T00:00:00+00:00"
            with patch(
                "custom_components.charge_tally.ledger.json.loads", wraps=json.loads
            ) as loads:
                self.assertEqual(
                    [
                        v["id"]
                        for v in ledger.list_price_versions("p", start=start, end=end)
                    ],
                    ["pb"],
                )
                self.assertEqual(loads.call_count, 1)
            with patch(
                "custom_components.charge_tally.ledger.json.loads", wraps=json.loads
            ) as loads:
                self.assertEqual(
                    [v["id"] for v in ledger.list_intervals("p", start, end)], ["p2"]
                )
                self.assertEqual(loads.call_count, 1)
            self.assertEqual(
                [v["id"] for v in ledger.list_price_versions("p")],
                ["pz", "pa", "pb", "pc"],
            )
            self.assertEqual(
                [
                    v["id"]
                    for v in ledger.list_price_versions(
                        "p",
                        start="2025-12-31T00:00:00+00:00",
                        end="2026-01-03T00:00:00+00:00",
                    )
                ],
                ["pz", "pa", "pb"],
            )
            self.assertEqual(
                [
                    v["id"]
                    for v in ledger.list_price_versions(
                        "p",
                        start="2026-01-02T00:00:00+00:00",
                        end="2026-01-04T00:00:00+00:00",
                    )
                ],
                ["pb", "pc"],
            )
            statements = []
            ledger._db.set_trace_callback(statements.append)
            ledger.list_price_versions("p", start=start, end=end)
            ledger.list_intervals("p", start, end)
            ledger._db.set_trace_callback(None)
            for table, index in (
                ("price_versions", "price_time"),
                ("observations", "observation_end"),
            ):
                query = next(
                    sql
                    for sql in statements
                    if sql.startswith(f"SELECT data FROM {table}")
                )
                plan = ledger._db.execute("EXPLAIN QUERY PLAN " + query).fetchall()
                self.assertTrue(
                    any(
                        "SEARCH" in row[-1]
                        and index in row[-1]
                        and "<expr>>?" in row[-1]
                        for row in plan
                    ),
                    plan,
                )

    def test_record_filters_exclude_history_and_unauthorized_points_before_decode(self):
        import json

        with closing(Ledger(":memory:")) as ledger:
            ledger.put_identity({"id": "i", "name": "Identity"})
            for point in ("p", "other"):
                ledger.put_point({"id": point})
                for day, status in ((1, "ended"), (2, "active")):
                    ledger.save_record(
                        dict(
                            id=point + str(day),
                            point_id=point,
                            identity_id="i",
                            start=f"2026-01-0{day}T00:00:00+00:00",
                            end=None
                            if status == "active"
                            else "2026-01-01T01:00:00+00:00",
                            status=status,
                            revision=1,
                        ),
                        [],
                    )
            with patch(
                "custom_components.charge_tally.ledger.json.loads", wraps=json.loads
            ) as loads:
                self.assertEqual(
                    [
                        r["id"]
                        for r in ledger.list_records(point_ids={"p"}, status="active")
                    ],
                    ["p2"],
                )
                self.assertEqual(loads.call_count, 1)
            self.assertEqual(
                [
                    r["id"]
                    for r in ledger.list_records(
                        point_id="p",
                        start="2026-01-01T01:00:00+00:00",
                        end="2026-01-03T00:00:00+00:00",
                    )
                ],
                ["p2"],
            )
            self.assertEqual(ledger.list_records(point_ids=set()), [])

    def test_prune_recent_observations_does_no_candidate_reference_work(self):
        from datetime import timedelta

        with closing(Ledger(":memory:")) as ledger:
            ledger.put_point({"id": "p"})
            for index in range(1000):
                left = datetime(2026, 10, 1, tzinfo=UTC) + timedelta(seconds=index * 5)
                ledger._put(
                    "observations",
                    str(index),
                    {
                        "id": str(index),
                        "point_id": "p",
                        "start": left.isoformat(),
                        "end": (left + timedelta(seconds=5)).isoformat(),
                    },
                )
            statements = []
            ledger._db.set_trace_callback(statements.append)
            self.assertEqual(ledger.prune(datetime(2026, 1, 1, tzinfo=UTC)), 0)
            ledger._db.set_trace_callback(None)
            self.assertFalse(
                any("FROM segments WHERE observation_id=" in sql for sql in statements)
            )
            candidate_query = next(
                sql
                for sql in statements
                if sql.startswith("SELECT data FROM observations")
            )
            candidate_plan = ledger._db.execute(
                "EXPLAIN QUERY PLAN " + candidate_query
            ).fetchall()
            self.assertTrue(
                any(
                    "SEARCH" in row[-1] and "observation_end" in row[-1]
                    for row in candidate_plan
                )
            )
            self.assertFalse(
                any(
                    sql == "SELECT data FROM observations ORDER BY id"
                    for sql in statements
                )
            )
            plan = ledger._db.execute(
                "EXPLAIN QUERY PLAN SELECT 1 FROM segments WHERE observation_id=? LIMIT 1",
                ("absent",),
            ).fetchall()
            self.assertTrue(
                any("SEARCH" in row[-1] and "observation" in row[-1] for row in plan)
            )

    def test_prune_candidate_budget_advances_past_protected_rows(self):
        with closing(Ledger(":memory:")) as ledger:
            ledger.put_point({"id": "p"})
            for index in range(5):
                ledger.put_interval(
                    {
                        "id": str(index),
                        "point_id": "p",
                        "start": f"2025-01-0{index + 1}T00:00:00+00:00",
                        "end": f"2025-01-0{index + 1}T01:00:00+00:00",
                        "gap": index < 3,
                    }
                )
            cutoff = datetime(2026, 1, 1, tzinfo=UTC)
            self.assertEqual(ledger.prune(cutoff, limit=2), 0)
            self.assertTrue(ledger.prune_pending())
            statements = []
            ledger._db.set_trace_callback(statements.append)
            self.assertEqual(ledger.prune(cutoff, limit=2), 1)
            ledger._db.set_trace_callback(None)
            query = next(
                sql
                for sql in statements
                if sql.startswith("SELECT data FROM observations")
            )
            plan = ledger._db.execute("EXPLAIN QUERY PLAN " + query).fetchall()
            self.assertTrue(
                any(
                    "SEARCH" in row[-1]
                    and "observation_end" in row[-1]
                    and "<expr>>?" in row[-1]
                    for row in plan
                ),
                plan,
            )
            self.assertTrue(ledger.prune_pending())
            self.assertEqual(ledger.prune(cutoff, limit=2), 1)
            self.assertFalse(ledger.prune_pending())
            self.assertEqual(
                [v["id"] for v in ledger.list_intervals("p")], ["0", "1", "2"]
            )

    def test_prune_seeks_only_old_prices_before_reference_work(self):
        with closing(Ledger(":memory:")) as ledger:
            ledger.put_point({"id": "p"})
            for index in range(1000):
                ledger._put(
                    "price_versions",
                    str(index),
                    {
                        "id": str(index),
                        "point_id": "p",
                        "at": "2026-10-30T00:00:00+00:00",
                        "price": "2",
                    },
                )
            statements = []
            ledger._db.set_trace_callback(statements.append)
            self.assertEqual(ledger.prune(datetime(2026, 1, 1, tzinfo=UTC)), 0)
            ledger._db.set_trace_callback(None)
            query = next(
                sql
                for sql in statements
                if sql.startswith("SELECT data FROM price_versions")
            )
            plan = ledger._db.execute("EXPLAIN QUERY PLAN " + query).fetchall()
            self.assertTrue(
                any(
                    "SEARCH" in row[-1]
                    and "price_" in row[-1]
                    and "<expr><?" in row[-1]
                    for row in plan
                ),
                plan,
            )

    def test_price_candidate_budget_advances_past_a_protected_anchor(self):
        with closing(Ledger(":memory:")) as ledger:
            for point in ("protected", "idle"):
                ledger.put_point({"id": point})
            for id_, point, day in (
                ("keep", "protected", 1),
                ("old", "idle", 2),
                ("anchor", "idle", 3),
            ):
                ledger.put_price_version(
                    {
                        "id": id_,
                        "point_id": point,
                        "at": f"2025-01-0{day}T00:00:00+00:00",
                        "price": "2",
                    }
                )
            cutoff = datetime(2026, 1, 1, tzinfo=UTC)
            self.assertEqual(ledger.prune(cutoff, limit=1), 0)
            self.assertTrue(ledger.prune_pending())
            self.assertEqual(ledger.prune(cutoff, limit=1), 1)
            self.assertTrue(ledger.prune_pending())
            self.assertEqual(ledger.prune(cutoff, limit=1), 0)
            self.assertFalse(ledger.prune_pending())
            self.assertEqual(
                [p["id"] for p in ledger.list_price_versions("protected")], ["keep"]
            )
            self.assertEqual(
                [p["id"] for p in ledger.list_price_versions("idle")], ["anchor"]
            )

    def test_commit_failure_rolls_back_and_next_write_is_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "ledger.db")
            with closing(Ledger(path)) as ledger:
                ledger.put_checkpoint("cursor", 1)
                ledger._db.execute("PRAGMA busy_timeout=0")
                with closing(sqlite3.connect(path, isolation_level=None)) as reader:
                    reader.execute("BEGIN")
                    reader.execute("SELECT * FROM checkpoints").fetchall()
                    with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                        ledger.put_checkpoint("cursor", 2)
                    reader.execute("ROLLBACK")
                with self.subTest(
                    "failed commit leaves no transaction or partial write"
                ):
                    self.assertFalse(ledger._db.in_transaction)
                    self.assertEqual(ledger.get_checkpoint("cursor"), 1)
                ledger.put_checkpoint("next", 3)
            with closing(Ledger(path)) as restored:
                self.assertEqual(restored.get_checkpoint("cursor"), 1)
                self.assertEqual(restored.get_checkpoint("next"), 3)

    def test_nested_rollback_preserves_outer_transaction(self):
        with closing(Ledger(":memory:")) as ledger:
            with ledger.transaction():
                ledger.put_checkpoint("before", 1)
                with self.assertRaisesRegex(ValueError, "inner failure"):
                    with ledger.transaction():
                        ledger.put_checkpoint("discarded", 2)
                        raise ValueError("inner failure")
                self.assertTrue(ledger._db.in_transaction)
                self.assertEqual(ledger.get_checkpoint("before"), 1)
                self.assertIsNone(ledger.get_checkpoint("discarded"))
                ledger.put_checkpoint("after", 3)
            self.assertFalse(ledger._db.in_transaction)
            self.assertEqual(ledger.get_checkpoint("before"), 1)
            self.assertEqual(ledger.get_checkpoint("after"), 3)
            self.assertIsNone(ledger.get_checkpoint("discarded"))

    def test_observation_overlap_uses_indexed_exists_and_keeps_id_conflict(self):
        from datetime import timedelta
        from decimal import Decimal

        from custom_components.charge_tally.accounting import Accounting

        with closing(Ledger(":memory:")) as ledger:
            ledger.put_point({"id": "p", "name": "Point"})
            app = Accounting(ledger)
            start = datetime(2026, 1, 1, tzinfo=UTC)
            app.add_interval("p", start, start + timedelta(seconds=5), Decimal("1"), [])
            statements = []
            ledger._db.set_trace_callback(statements.append)
            app.add_interval(
                "p",
                start + timedelta(seconds=5),
                start + timedelta(seconds=10),
                Decimal("1"),
                [],
            )
            ledger._db.set_trace_callback(None)
            query = next(
                statement
                for statement in statements
                if "SELECT EXISTS(SELECT 1 FROM observations" in statement
            )
            plan = ledger._db.execute("EXPLAIN QUERY PLAN " + query).fetchall()
            self.assertTrue(
                any("SEARCH" in row[-1] and "observation_" in row[-1] for row in plan)
            )
            self.assertFalse(
                any(
                    statement.startswith(
                        "SELECT data FROM observations WHERE json_extract"
                    )
                    for statement in statements
                )
            )
            with self.assertRaisesRegex(ValueError, "immutable"):
                app.add_interval(
                    "p", start, start + timedelta(seconds=5), Decimal("2"), []
                )
            with self.assertRaisesRegex(ValueError, "overlap"):
                app.add_interval(
                    "p",
                    start + timedelta(seconds=1),
                    start + timedelta(seconds=3),
                    Decimal("1"),
                    [],
                )

    def test_explicit_snapshot_reads_current_sparse_version_atomically(self):
        with closing(Ledger(":memory:")) as ledger:
            ledger.put_identity({"id": "i", "name": "Identity"})
            ledger.put_point({"id": "p", "name": "Point"})
            record = dict(
                id="r",
                point_id="p",
                identity_id="i",
                start="2026-01-01T00:00:00+00:00",
                end=None,
                status="active",
                revision=1,
            )
            ledger.save_record(record, [])
            ledger.save_record(dict(record, revision=4), [], audit=False)
            with self.assertRaisesRegex(ValueError, "transaction"):
                ledger.save_revision("r")
            with ledger.transaction():
                ledger.save_revision("r")
            self.assertEqual(
                [r["record"]["revision"] for r in ledger.list_revisions("r")], [1, 4]
            )

    def test_currency_change_only_before_accounting_use(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            closing(Ledger(str(Path(directory) / "ledger.db"))) as ledger,
        ):
            ledger.bind_currency("CNY")
            ledger.put_identity({"id": "car", "name": "Car"})
            self.assertTrue(ledger.currency_change_allowed())
            ledger.change_currency("USD", "CNY")
            self.assertEqual(ledger.currency, "USD")
            self.assertEqual(ledger.get_identity("car")["name"], "Car")
            with self.assertRaisesRegex(ValueError, "config_changed"):
                ledger.change_currency("EUR", "CNY")
            with self.assertRaisesRegex(ValueError, "invalid_currency"):
                ledger.change_currency("bad unit", "USD")
            ledger.put_point({"id": "old", "name": "Old", "active": False})
            self.assertFalse(ledger.currency_change_allowed())
            with self.assertRaisesRegex(ValueError, "currency_locked"):
                ledger.change_currency("EUR", "USD")
            self.assertEqual(ledger.currency, "USD")
            ledger.close()

    def test_roundtrip_rollback_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "ledger.db")
            ledger = Ledger(path)
            ledger.put_identity({"id": "personal", "name": "Personal"})
            ledger.put_point({"id": "home", "name": "Home"})
            with self.assertRaises(ValueError):
                with ledger.transaction():
                    ledger.put_checkpoint("home", {"cursor": 3})
                    ledger.put_identity({"id": "temporary", "name": "Temporary"})
                    raise ValueError("Injected application failure")
            self.assertIsNone(ledger.get_checkpoint("home"))
            self.assertIsNone(ledger.get_identity("temporary"))
            ledger.put_checkpoint("home", {"cursor": 4})
            ledger.put_price_version(
                {
                    "id": "price1",
                    "point_id": "home",
                    "at": "2026-01-01T00:00:00+00:00",
                    "price": "-1",
                }
            )
            backup = str(Path(directory) / "backup.db")
            ledger.backup(backup)
            ledger.close()
            for filename in (path, backup):
                restored = Ledger(filename)
                self.assertEqual(restored.get_checkpoint("home"), {"cursor": 4})
                self.assertEqual(restored.list_identities()[0]["name"], "Personal")
                self.assertEqual(restored.list_points()[0]["name"], "Home")
                self.assertEqual(restored.list_price_versions("home")[0]["price"], "-1")
                restored.close()

    def test_prune_old_unreferenced_prices_keeps_effective_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(str(Path(directory) / "ledger.db"))
            try:
                ledger.put_point({"id": "home", "name": "Home"})
                for index, date in enumerate(
                    ("2025-01-01", "2025-02-01", "2026-08-01")
                ):
                    ledger.put_price_version(
                        {
                            "id": str(index),
                            "point_id": "home",
                            "at": date + "T00:00:00+00:00",
                            "price": str(index),
                        }
                    )
                self.assertEqual(ledger.prune(datetime(2026, 1, 1, tzinfo=UTC)), 1)
                self.assertEqual(
                    [p["id"] for p in ledger.list_price_versions("home")], ["1", "2"]
                )
            finally:
                ledger.close()

    def test_archived_identity_name_can_be_reused_without_reassigning_history(self):
        ledger = Ledger(":memory:")
        self.addCleanup(ledger.close)
        ledger.put_identity({"id": "old", "name": "Personal", "active": False})
        ledger.put_identity({"id": "new", "name": "Personal"})
        self.assertFalse(ledger.get_identity("old")["active"])
        self.assertEqual(ledger.get_identity("new")["name"], "Personal")
        with self.assertRaises(ValueError):
            ledger.put_identity({"id": "third", "name": "Personal"})
        with self.assertRaises(ValueError):
            ledger.put_identity({"id": "old", "name": "Personal", "active": True})

    def test_price_prune_protects_actual_record_range_and_anchor_only(self):
        from custom_components.charge_tally.accounting import Accounting

        ledger = Ledger(":memory:")
        self.addCleanup(ledger.close)
        ledger.put_identity({"id": "personal", "name": "Personal"})
        ledger.put_point({"id": "home", "name": "Home"})
        for day in (1, 2, 3):
            ledger.put_price_version(
                {
                    "id": str(day),
                    "point_id": "home",
                    "at": f"2026-01-0{day}T00:00:00+00:00",
                    "price": str(day),
                }
            )
        app = Accounting(ledger)
        preview = app.preview(
            {
                "point_id": "home",
                "identity_id": "personal",
                "start": "2026-01-01T00:00:00+00:00",
                "end": "2026-01-01T01:00:00+00:00",
                "energy_kwh": "1",
            }
        )
        app.commit_preview(preview["token"], "save")
        self.assertEqual(ledger.prune(datetime(2026, 8, 1, tzinfo=UTC)), 1)
        self.assertEqual(
            [p["id"] for p in ledger.list_price_versions("home")], ["1", "3"]
        )
        missing = app.preview(
            {
                "point_id": "home",
                "identity_id": "personal",
                "start": "2026-01-02T00:00:00+00:00",
                "end": "2026-01-02T01:00:00+00:00",
                "energy_kwh": "1",
            }
        )
        self.assertFalse(missing["record"]["cost_complete"])
        self.assertIsNone(missing["segments"][0]["cost"])
