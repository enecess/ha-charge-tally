"""Period report rows share the exact original-segment summary projection."""

import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_accounting as fixtures

from custom_components.charge_tally.queries import summarize

T = fixtures.T


class ReportTests(unittest.TestCase):
    setUp = fixtures.AccountingTests.setUp
    manual = fixtures.AccountingTests.manual

    def report(self, start=None, end=None, **kwargs):
        from custom_components.charge_tally.reports import build_report

        with self.ledger.transaction():
            summary = summarize(self.ledger, start, end, include_records=True, **kwargs)
            return build_report(
                self.ledger,
                summary,
                scope={
                    "calendar": kwargs.get("calendar"),
                    "point_id": None,
                    "identity_id": None,
                },
                currency="CNY",
                timezone=kwargs.get("timezone", "UTC"),
                generated_at=T,
            )

    def cross_month(self):
        start = datetime(2025, 10, 31, 23, tzinfo=UTC)
        middle, end = start + timedelta(hours=1), start + timedelta(hours=2)
        self.ledger.put_point(
            {**self.ledger.get_point("home"), "max_interval_seconds": 7200}
        )
        record = self.app.start("home", "personal", start, "start", timezone="UTC")
        for left, right, amount in [(start, middle, "1"), (middle, end, "9")]:
            self.app.add_interval(
                "home", left, right, Decimal(amount), [(left, Decimal("2"))]
            )
        record = self.app.end(record["id"], end, "end")
        return start, middle, end, record

    def test_cross_month_rows_use_original_samples_and_keep_full_record(self):
        start, middle, end, record = self.cross_month()
        self.assertEqual(len(self.ledger.list_segments(record["id"])), 2)
        for label, left, right, energy, cost in [
            ("2025-10", start, middle, 1, 2),
            ("2025-11", middle, end, 9, 18),
        ]:
            with self.subTest(label=label):
                report = self.report(calendar=label)
                expected = summarize(self.ledger, None, None, calendar=label)
                self.assertEqual(report["summary"], expected)
                self.assertEqual(
                    report["summary"]["matched_count"], len(report["rows"])
                )
                self.assertEqual(len(report["rows"]), 1)
                row = report["rows"][0]
                self.assertEqual(Decimal(row["energy_kwh"]), energy)
                self.assertEqual(Decimal(row["known_cost"]), cost)
                self.assertEqual(row["record"]["start"], record["start"])
                self.assertEqual(row["record"]["end"], record["end"])
                self.assertEqual(row["range_start"], left.isoformat())
                self.assertEqual(row["range_end"], right.isoformat())
                self.assertNotIn("_accounted_until", row["record"])
                self.assertNotIn("records", report["summary"])
                self.assertNotIn("offset", report)
                self.assertNotIn("limit", report)

    def test_record_projection_does_not_change_default_summary(self):
        self.cross_month()
        default = summarize(self.ledger, T - timedelta(days=100), T)
        projected = summarize(
            self.ledger, T - timedelta(days=100), T, include_records=True
        )
        rows = projected.pop("records")
        self.assertEqual(projected, default)
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            set(rows[0]),
            {
                "record",
                "range_start",
                "range_end",
                "energy_kwh",
                "known_cost",
                "cost_complete",
                "quality",
                "has_energy_data",
                "has_known_cost",
            },
        )
        with patch.object(
            self.ledger, "list_segments", wraps=self.ledger.list_segments
        ) as segments:
            self.report()
            self.assertEqual(segments.call_count, 1)

    def test_clipped_quality_ignores_missing_price_and_energy_outside_range(self):
        record = self.app.start("home", "personal", T, "start")
        self.app.add_interval(
            "home",
            T,
            T + timedelta(seconds=20),
            Decimal("2"),
            [(T, Decimal("2")), (T + timedelta(seconds=10), None)],
        )
        self.app.end(record["id"], T + timedelta(seconds=30), "end")
        row = self.report(T, T + timedelta(seconds=10))["rows"][0]
        self.assertEqual(Decimal(row["energy_kwh"]), 1)
        self.assertEqual(Decimal(row["known_cost"]), 2)
        self.assertTrue(row["cost_complete"])
        self.assertNotIn("missing_price", row["quality"])
        self.assertNotIn("missing_energy", row["quality"])
        for left, right, mark, has_energy in [
            (10, 20, "missing_price", True),
            (20, 30, "missing_energy", False),
        ]:
            clipped = self.report(
                T + timedelta(seconds=left), T + timedelta(seconds=right)
            )
            row = clipped["rows"][0]
            self.assertFalse(row["cost_complete"])
            self.assertIn(mark, row["quality"])
            self.assertIn(mark, clipped["summary"]["quality"])
            self.assertEqual(row["has_energy_data"], has_energy)
            self.assertFalse(row["has_known_cost"])

    def test_active_no_samples_and_real_zero_are_distinct(self):
        record = self.app.start("home", "personal", T, "start")
        pending = self.report()["rows"][0]
        self.assertIsNone(pending["range_end"])
        self.assertIsNone(pending["record"]["end"])
        self.assertFalse(pending["has_energy_data"])
        self.assertFalse(pending["has_known_cost"])
        self.assertIn("provisional", pending["quality"])
        self.app.add_interval(
            "home", T, T + timedelta(seconds=10), Decimal(0), [(T, Decimal(0))]
        )
        zero = self.report(T, T + timedelta(seconds=10))["rows"][0]
        self.assertEqual(zero["record"]["id"], record["id"])
        self.assertIsNone(zero["record"]["end"])
        self.assertEqual(zero["range_end"], (T + timedelta(seconds=10)).isoformat())
        self.assertTrue(zero["has_energy_data"])
        self.assertTrue(zero["has_known_cost"])
        self.assertTrue(zero["cost_complete"])
        self.assertEqual(Decimal(zero["energy_kwh"]), 0)
        self.assertEqual(Decimal(zero["known_cost"]), 0)

    def test_manual_negative_cost_void_and_empty_report(self):
        record = self.app.commit_preview(
            self.app.preview(
                self.manual(
                    start=T - timedelta(hours=1), end=T + timedelta(hours=2), cost="-6"
                )
            )["token"],
            "save",
        )
        report = self.report(T, T + timedelta(hours=1))
        row = report["rows"][0]
        self.assertEqual(Decimal(row["energy_kwh"]), 7)
        self.assertEqual(Decimal(row["known_cost"]), -2)
        self.assertTrue(row["cost_complete"])
        self.assertIn("estimated", row["quality"])
        self.assertEqual(row["record"]["note"], "manual")
        self.assertEqual(report["summary"]["completed_count"], 0)
        self.app.void(record["id"], record["revision"])
        empty = self.report()
        self.assertEqual(empty["rows"], [])
        self.assertEqual(empty["summary"]["matched_count"], 0)
        self.assertFalse(empty["summary"]["has_energy_data"])

    def test_report_is_an_independent_named_versioned_snapshot(self):
        self.cross_month()
        before = list(self.ledger._db.iterdump())
        version = self.ledger.data_version()
        report = self.report()
        original = deepcopy(report)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["generated_at"], T.isoformat())
        self.assertEqual(report["data_version"], version)
        self.assertEqual(report["currency"], "CNY")
        self.assertEqual(report["timezone"], "UTC")
        self.assertEqual(report["rows"][0]["point_name"], "home")
        self.assertEqual(report["rows"][0]["identity_name"], "personal")
        self.assertEqual(list(self.ledger._db.iterdump()), before)
        self.ledger.put_point({"id": "home", "name": "Renamed"})
        self.assertEqual(report, original)
        report["rows"][0]["record"]["quality"].append("changed")
        self.assertNotIn("changed", self.ledger.list_records()[0]["quality"])

    def test_report_contains_all_101_records_without_pagination(self):
        for index in range(101):
            left = T + timedelta(minutes=index)
            record = self.app.preview(
                self.manual(
                    start=left,
                    end=left + timedelta(seconds=30),
                    energy_kwh="1",
                    cost="2",
                )
            )
            self.app.commit_preview(record["token"], str(index))
        result = self.report()
        self.assertEqual(len(result["rows"]), 101)
        self.assertEqual(result["summary"]["matched_count"], 101)
        self.assertEqual(Decimal(result["summary"]["energy_kwh"]), 101)
        self.assertEqual(Decimal(result["summary"]["known_cost"]), 202)

    def test_report_timezone_contract(self):
        cases = [
            (
                "year",
                "Asia/Shanghai",
                "2025-12-31T23:00:00+08:00",
                "2026-01-01T02:00:00+08:00",
                "2026",
                "3",
                "2",
                "-2",
                0,
            ),
            (
                "fold",
                "America/New_York",
                "2025-11-02T00:00:00-04:00",
                "2025-11-03T00:00:00-05:00",
                "2025-11-02",
                "25",
                "25",
                "-25",
                1,
            ),
            (
                "gap",
                "America/New_York",
                "2026-03-08T00:00:00-05:00",
                "2026-03-09T00:00:00-04:00",
                "2026-03-08",
                "23",
                "23",
                "-23",
                1,
            ),
            (
                "half",
                "Australia/Lord_Howe",
                "2026-04-05T00:00:00+11:00",
                "2026-04-06T00:00:00+10:30",
                "2026-04-05",
                "49",
                "49",
                "-49",
                1,
            ),
        ]
        for point, zone, start, end, label, total, expected, fee, count in cases:
            with self.subTest(point=point):
                self.ledger.put_point({"id": point, "name": point})
                preview = self.app.preview(
                    self.manual(
                        point_id=point,
                        start=datetime.fromisoformat(start),
                        end=datetime.fromisoformat(end),
                        timezone=zone,
                        energy_kwh=total,
                        cost=str(-Decimal(total)),
                    )
                )
                self.app.commit_preview(preview["token"], point)
                result = self.report(calendar=label, point_id=point, timezone=zone)
                self.assertEqual(
                    result["summary"],
                    summarize(
                        self.ledger,
                        None,
                        None,
                        calendar=label,
                        point_id=point,
                        timezone=zone,
                    ),
                )
                row = result["rows"][0]
                self.assertEqual(Decimal(row["energy_kwh"]), Decimal(expected))
                self.assertEqual(Decimal(row["known_cost"]), Decimal(fee))
                self.assertEqual(row["record"]["timezone"], zone)
                self.assertEqual(result["timezone"], zone)
                self.assertEqual(result["summary"]["completed_count"], count)
                if point == "fold":
                    self.assertEqual(len(result["summary"]["buckets"]), 25)
                if point == "gap":
                    self.assertEqual(len(result["summary"]["buckets"]), 23)
                if point == "half":
                    self.assertEqual(len(result["summary"]["buckets"]), 25)
        for point, zone, expected in [
            ("home", "UTC", "1"),
            ("work", "Asia/Shanghai", "2"),
        ]:
            start = datetime(2025, 12, 31, 23, tzinfo=ZoneInfo(zone))
            preview = self.app.preview(
                self.manual(
                    point_id=point,
                    start=start,
                    end=start + timedelta(hours=2),
                    timezone=zone,
                    energy_kwh=str(Decimal(expected) * 2),
                    cost="0",
                )
            )
            self.app.commit_preview(preview["token"], point)
        mixed = self.report(calendar="2026-01-01", identity_id="personal")
        rows = {r["record"]["point_id"]: r for r in mixed["rows"]}
        self.assertEqual(Decimal(rows["home"]["energy_kwh"]), 1)
        self.assertNotIn("work", rows)
        self.assertEqual(rows["home"]["range_start"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(
            self.ledger.list_records(point_id="work")[0]["timezone"], "Asia/Shanghai"
        )

    def test_build_report_does_not_mutate_source_summary_or_scope(self):
        from custom_components.charge_tally.reports import build_report

        self.cross_month()
        summary = summarize(self.ledger, None, None, include_records=True)
        scope = {"point_id": "home", "identity_id": "personal", "calendar": None}
        original_summary, original_scope = deepcopy(summary), deepcopy(scope)
        with self.ledger.transaction():
            report = build_report(
                self.ledger,
                summary,
                scope=scope,
                currency="CNY",
                timezone="UTC",
                generated_at=T,
            )
        self.assertEqual(summary, original_summary)
        self.assertEqual(scope, original_scope)
        report["rows"][0]["record"]["quality"].append("changed")
        report["summary"]["quality"].append("changed")
        report["scope"]["point_id"] = "changed"
        self.assertEqual(summary, original_summary)
        self.assertEqual(scope, original_scope)
