"""Calendar buckets preserve clock boundaries and elapsed durations."""

import unittest
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.charge_tally.core.buckets import (
    bucket_windows,
    choose_bucket_period,
)


class BucketTests(unittest.TestCase):
    def test_calendar_and_custom_periods(self):
        for calendar, expected in [
            ("2026-01-01", "hour"),
            ("2026-01", "day"),
            ("2026", "month"),
            (None, "year"),
        ]:
            self.assertEqual(
                choose_bucket_period(
                    "auto", calendar=calendar, start=None, end=None, timezone="UTC"
                ),
                expected,
            )
        start = datetime(2026, 1, 1, tzinfo=UTC)
        for days, expected in [
            (2, "hour"),
            (3, "day"),
            (90, "day"),
            (91, "month"),
            (730, "month"),
            (731, "year"),
        ]:
            self.assertEqual(
                choose_bucket_period(
                    "auto",
                    calendar=None,
                    start=start,
                    end=start + timedelta(days=days),
                    timezone="UTC",
                ),
                expected,
            )
        for month, day in [(3, 7), (10, 31)]:
            start = datetime(2026, month, day, tzinfo=ZoneInfo("America/New_York"))
            self.assertEqual(
                choose_bucket_period(
                    "auto",
                    calendar=None,
                    start=start,
                    end=start + timedelta(days=2),
                    timezone="America/New_York",
                ),
                "hour",
            )

    def test_dst_and_outer_hour_boundaries(self):
        zone = "America/New_York"
        for month, day, count in [(3, 8, 23), (11, 1, 25)]:
            start = datetime(2026, month, day, tzinfo=ZoneInfo(zone))
            windows = bucket_windows(start, start + timedelta(days=1), zone, "hour")
            self.assertEqual(len(windows), count)
            self.assertEqual(len({w.key for w in windows}), count)
            hours = [w.start.astimezone(ZoneInfo(zone)).hour for w in windows]
            self.assertEqual(hours.count(1), 2 if month == 11 else 1)
            if month == 3:
                self.assertNotIn(2, hours)
        start = datetime(2026, 1, 1, 0, 5, tzinfo=UTC)
        first = bucket_windows(start, start + timedelta(minutes=5), "UTC", "hour")[0]
        second = bucket_windows(
            start + timedelta(minutes=10), start + timedelta(minutes=15), "UTC", "hour"
        )[0]
        self.assertEqual(first, second)
        self.assertEqual(first.start.minute, 0)
        self.assertEqual(first.end.hour, 1)

    def test_lord_howe_half_hour(self):
        start = datetime(2026, 4, 5, tzinfo=ZoneInfo("Australia/Lord_Howe"))
        windows = bucket_windows(
            start, start + timedelta(days=1), "Australia/Lord_Howe", "hour"
        )
        self.assertEqual(
            sum((w.end - w.start).total_seconds() for w in windows), 24.5 * 3600
        )

    def test_invalid(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        for period in ["auto", "bad"]:
            with self.assertRaises(ValueError):
                bucket_windows(start, start + timedelta(hours=1), "UTC", period)
        with self.assertRaises(ValueError):
            bucket_windows(start, start, "UTC", "hour")
