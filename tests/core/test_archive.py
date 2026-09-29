"""Archive deletion against real SQLite, including rollback and audit retention."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from custom_components.charge_tally.archive import ArchiveManager
from custom_components.charge_tally.ledger import Ledger


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(":memory:")
        self.addCleanup(self.ledger.close)
        self.ledger.bind_currency("CNY")
        for id_, active in [
            ("old", False),
            ("new", True),
            ("disabled", False),
            ("unassigned", True),
        ]:
            self.ledger.put_identity(dict(id=id_, name=id_.title(), active=active))
        for id_, active in [("oldpoint", False), ("live", True)]:
            self.ledger.put_point(dict(id=id_, name=id_.title(), active=active))
        self.manager = ArchiveManager(self.ledger)
        self.points, self.identities = {"live"}, {"new", "disabled"}

    def record(self, id_="r", point="oldpoint", identity="old", status="ended"):
        record = dict(
            id=id_,
            point_id=point,
            identity_id=identity,
            status=status,
            start="2026-01-01T00:00:00+00:00",
            end="2026-01-01T01:00:00+00:00",
            revision=1,
            energy_kwh="2.5",
            known_cost="1.25",
            cost_complete=True,
        )
        self.ledger.save_record(
            record,
            [
                dict(
                    energy_kwh="2.5", cost="1.25", unit_price="0.5", cost_basis="tariff"
                )
            ],
        )
        return record

    def preview(self, kind="point", id_="oldpoint", target=None):
        return self.manager.preview(kind, id_, self.points, self.identities, target)

    def delete(self, preview):
        return self.manager.delete(
            preview["kind"],
            preview["id"],
            preview["fingerprint"],
            self.points,
            self.identities,
            preview["target_identity_id"],
        )

    def test_catalog_and_protection(self):
        self.assertEqual(
            [
                x["id"]
                for x in self.manager.catalog(self.points, self.identities)[
                    "identities"
                ]
            ],
            ["old"],
        )
        for kind, id_ in [
            ("point", "live"),
            ("identity", "disabled"),
            ("identity", "unassigned"),
        ]:
            with self.assertRaisesRegex(ValueError, "archive_configured"):
                self.preview(kind, id_)

    def test_active_identity_still_cannot_be_transferred(self):
        self.record(status="active")
        with self.assertRaisesRegex(ValueError, "archive_busy"):
            self.preview("identity", "old", "new")

    def test_archived_point_with_active_record_can_be_confirmed_and_deleted(self):
        record = self.record(status="active")
        record.update(end=None, revision=2)
        self.ledger.save_record(record, self.ledger.list_segments(record["id"]))
        preview = self.preview()
        self.assertEqual(preview["active_count"], 1)
        self.assertIsNone(preview["end"])
        self.assertIsNone(preview["latest_ended_at"])
        self.assertIsNotNone(self.ledger.get_record(record["id"]))
        self.delete(preview)
        self.assertIsNone(self.ledger.get_point("oldpoint"))
        self.assertIsNone(self.ledger.get_record(record["id"]))

    def test_mixed_records_do_not_hide_unfinished_time_range(self):
        ended = self.record("ended")
        active = dict(ended, id="active", status="active", start=ended["end"], end=None)
        self.ledger.save_record(active, [])
        preview = self.preview()
        self.assertEqual(preview["active_count"], 1)
        self.assertIsNone(preview["end"])
        self.assertEqual(preview["latest_ended_at"], ended["end"])

    def test_ended_records_keep_actual_time_range(self):
        ended = self.record()
        preview = self.preview()
        self.assertEqual(preview["active_count"], 0)
        self.assertEqual(preview["end"], ended["end"])
        self.assertEqual(preview["latest_ended_at"], ended["end"])

    def test_point_cascade_and_currency_stays_locked(self):
        self.record()
        self.record("v", status="void")
        self.ledger._put("observations", "obs", dict(id="obs", point_id="oldpoint"))
        self.ledger._put("observation_resolutions", "obs", {"interval_ids": []})
        record = self.ledger.get_record("r")
        record["revision"] += 1
        self.ledger.save_record(
            record,
            [
                dict(
                    observation_id="obs",
                    energy_kwh="2.5",
                    cost="1.25",
                    unit_price="0.5",
                    cost_basis="tariff",
                )
            ],
        )
        self.ledger._put(
            "price_versions", "price", dict(id="price", point_id="oldpoint")
        )
        self.ledger._put("checkpoints", "_price_gaps:oldpoint", [])
        self.ledger.put_checkpoint("runtime", {"oldpoint": {}, "live": {}})
        self.ledger.put_request("req", {"result": self.ledger.get_record("r")})
        self.ledger.put_checkpoint("command_time:req", "time")
        self.ledger.put_preview("preview", {"record": self.ledger.get_record("r")})
        self.ledger.put_checkpoint("api_preview:preview", {"point_id": "oldpoint"})
        self.ledger.put_request("keep", {"result": {"point_id": "live"}})
        self.ledger.put_checkpoint(
            "api_request:keep", {"payload": {"point_id": "live"}}
        )
        summary = self.preview()
        self.assertEqual(
            (summary["record_count"], summary["void_count"], summary["known_cost"]),
            (2, 1, "2.50"),
        )
        self.delete(summary)
        for table in (
            "records",
            "segments",
            "revisions",
            "observations",
            "price_versions",
            "observation_resolutions",
            "previews",
        ):
            self.assertEqual(
                self.ledger._db.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
                0,
            )
        self.assertIsNone(self.ledger.get_request("req"))
        self.assertIsNone(self.ledger.get_checkpoint("command_time:req"))
        self.assertIsNone(self.ledger.get_checkpoint("api_preview:preview"))
        self.assertIsNotNone(self.ledger.get_request("keep"))
        self.assertIsNotNone(self.ledger.get_checkpoint("api_request:keep"))
        self.assertIn("live", self.ledger.get_checkpoint("runtime"))
        self.ledger._db.execute("DELETE FROM points")
        self.assertFalse(self.ledger.currency_change_allowed())
        self.assertEqual(
            self.ledger._db.execute("PRAGMA foreign_key_check").fetchall(), []
        )

    def test_identity_transfers_void_and_preserves_previous_audit(self):
        self.record(status="void")
        historical = self.record("history", point="live")
        historical.update(identity_id="new", revision=2)
        self.ledger.save_record(historical, self.ledger.list_segments("history"))
        original_segments = self.ledger.list_segments("r")
        summary = self.preview("identity", "old", "new")
        self.delete(summary)
        self.assertEqual(self.ledger.get_record("r")["identity_id"], "new")
        self.assertEqual(self.ledger.get_record("r")["revision"], 2)
        self.assertEqual(self.ledger.get_record("r")["status"], "void")
        self.assertEqual(self.ledger.list_segments("r"), original_segments)
        for id_ in ("r", "history"):
            old = self.ledger.list_revisions(id_)[0]["record"]
            self.assertEqual((old["identity_id"], old["identity_name"]), ("old", "Old"))
        self.assertIsNone(self.ledger.get_identity("old"))

    def test_identity_transfer_keeps_sparse_revision_numbers_and_old_name(self):
        record = self.record()
        record.update(revision=4, known_cost="3")
        self.ledger.save_record(record, self.ledger.list_segments("r"), audit=False)
        self.delete(self.preview("identity", "old", "new"))
        revisions = self.ledger.list_revisions("r")
        self.assertEqual([r["record"]["revision"] for r in revisions], [1, 5])
        self.assertEqual(revisions[0]["record"]["identity_name"], "Old")
        self.assertEqual(revisions[0]["record"]["known_cost"], "1.25")
        self.assertEqual(revisions[1]["record"]["identity_id"], "new")
        self.assertEqual(revisions[1]["record"]["known_cost"], "3")

    def test_target_required_and_validated(self):
        self.record()
        with self.assertRaisesRegex(ValueError, "archive_target"):
            self.delete(self.preview("identity", "old"))
        for target in ("disabled", "old", "missing"):
            with self.assertRaisesRegex(ValueError, "archive_target"):
                self.preview("identity", "old", target)
        self.delete(self.preview("identity", "old", "unassigned"))

    def test_fingerprint_relevant_changes_only(self):
        record = self.record()
        summary = self.preview()
        self.ledger.put_point(dict(id="live", name="Changed"))
        self.assertEqual(summary["fingerprint"], self.preview()["fingerprint"])
        record.update(revision=2, known_cost="2")
        self.ledger.save_record(record, [])
        with self.assertRaisesRegex(ValueError, "archive_stale"):
            self.delete(summary)

    def test_failure_rolls_back_everything(self):
        self.record()
        summary = self.preview("identity", "old", "new")
        with patch.object(self.ledger, "_bump", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.delete(summary)
        self.assertEqual(self.ledger.get_record("r")["identity_id"], "old")
        self.assertEqual(len(self.ledger.list_revisions("r")), 1)
        self.assertNotIn("identity_name", self.ledger.list_revisions("r")[0]["record"])
        self.assertIsNotNone(self.ledger.get_identity("old"))

    def test_identity_only_does_not_lock_currency(self):
        other = Ledger(":memory:")
        self.addCleanup(other.close)
        other.put_identity(dict(id="empty", name="Empty", active=False))
        manager = ArchiveManager(other)
        preview = manager.preview("identity", "empty", set(), set())
        manager.delete("identity", "empty", preview["fingerprint"], set(), set())
        self.assertTrue(other.currency_change_allowed())

    def test_empty_ledger_allows_currency_change_after_purge_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "ledger.db")
            ledger = Ledger(path)
            ledger.bind_currency("CNY")
            ledger.put_point(dict(id="old", name="Old", active=False))
            ledger.close()
            ledger = Ledger(path)
            manager = ArchiveManager(ledger)
            summary = manager.preview("point", "old", set(), set())
            manager.delete("point", "old", summary["fingerprint"], set(), set())
            ledger.close()
            ledger = Ledger(path)
            try:
                self.assertTrue(ledger.currency_change_allowed())
                ledger.change_currency("USD", "CNY")
                self.assertEqual(ledger.currency, "USD")
            finally:
                ledger.close()

    def test_target_change_invalidates_confirmation(self):
        self.record()
        summary = self.preview("identity", "old", "new")
        self.ledger.put_identity(dict(id="new", name="Renamed"))
        with self.assertRaisesRegex(ValueError, "archive_stale"):
            self.delete(summary)
        summary = self.preview("identity", "old", "new")
        self.identities.remove("new")
        with self.assertRaisesRegex(ValueError, "archive_target"):
            self.delete(summary)

    def test_request_checkpoint_chain_removed_selectively(self):
        record = self.record()
        self.ledger.put_preview("token", {"payload": {"record": record}})
        self.ledger.put_request("api:hash", {"result": record})
        self.ledger.put_checkpoint(
            "api_request:hash",
            {"payload": {"token": "token", "request_id": "external"}, "result": record},
        )
        self.ledger.put_checkpoint(
            "runtime_request:api:hash",
            {"payload": {"token": "token"}, "result": record},
        )
        self.ledger.put_checkpoint("command_time:api:hash", "time")
        self.ledger.put_checkpoint("command_time:external", "time")
        self.ledger.put_checkpoint("command_time:unrelated", "time")
        self.delete(self.preview("identity", "old", "new"))
        for key in (
            "api_request:hash",
            "runtime_request:api:hash",
            "command_time:api:hash",
            "command_time:external",
        ):
            self.assertIsNone(self.ledger.get_checkpoint(key), key)
        self.assertIsNotNone(self.ledger.get_checkpoint("command_time:unrelated"))
        self.assertIsNone(self.ledger.get_preview("token"))

    def test_point_purge_failure_restores_rows_and_caches(self):
        record = self.record()
        self.ledger.put_request("req", {"result": record})
        summary = self.preview()
        with patch.object(self.ledger, "_bump", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.delete(summary)
        self.assertIsNotNone(self.ledger.get_point("oldpoint"))
        self.assertIsNotNone(self.ledger.get_record("r"))
        self.assertIsNotNone(self.ledger.get_request("req"))
        self.assertEqual(len(self.ledger.list_revisions("r")), 1)
        self.assertEqual(
            self.ledger._db.execute("PRAGMA foreign_key_check").fetchall(), []
        )

    def test_point_purge_removes_moved_record_source_history_only(self):
        self.ledger._put(
            "observations", "oldobs", dict(id="oldobs", point_id="oldpoint")
        )
        self.ledger._put("observations", "liveobs", dict(id="liveobs", point_id="live"))
        record = self.record()
        record["revision"] = 2
        self.ledger.save_record(
            record,
            [
                dict(
                    observation_id="oldobs",
                    energy_kwh="2.5",
                    cost="1.25",
                    unit_price="0.5",
                    cost_basis="tariff",
                )
            ],
        )
        record.update(point_id="live", revision=3)
        segments = [
            dict(
                observation_id="liveobs",
                energy_kwh="2.5",
                cost="1.25",
                unit_price="0.5",
                cost_basis="tariff",
            )
        ]
        self.ledger.save_record(record, segments)
        self.ledger.put_request("moved", {"result": record})
        summary = self.preview()
        self.assertEqual(summary["record_count"], 0)
        self.assertEqual(summary["revision_count"], 2)
        self.delete(summary)
        self.assertEqual(self.ledger.get_record("r"), record)
        self.assertEqual(self.ledger.list_segments("r"), segments)
        self.assertEqual(
            [r["record"]["revision"] for r in self.ledger.list_revisions("r")], [3]
        )
        self.assertIsNone(self.ledger._get("observations", "oldobs"))
        self.assertIsNotNone(self.ledger._get("observations", "liveobs"))
        self.assertIsNone(self.ledger.get_request("moved"))
        for revision in self.ledger.list_revisions("r"):
            self.assertIsNotNone(self.ledger.get_point(revision["record"]["point_id"]))
            for segment in revision["segments"]:
                self.assertIsNotNone(
                    self.ledger._get("observations", segment["observation_id"])
                )
        self.assertEqual(
            self.ledger._db.execute("PRAGMA foreign_key_check").fetchall(), []
        )
