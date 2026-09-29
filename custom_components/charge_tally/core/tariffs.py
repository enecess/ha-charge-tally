"""Daily local-clock tariffs and calendar boundary handling."""

import re
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .units import decimal_value


def utc(at: datetime) -> datetime:
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("An aware datetime is required")
    return at.astimezone(UTC)


def elapsed(start: datetime, end: datetime) -> Decimal:
    delta = utc(end) - utc(start)
    return Decimal(delta.days * 86400 + delta.seconds) + Decimal(
        delta.microseconds
    ) / Decimal(1000000)


def calendar_boundaries(
    start: datetime,
    end: datetime,
    timezone: str,
    minutes: set[int],
    *,
    clock_changes: bool = False,
) -> list[datetime]:
    """Resolve both folds and skip nonexistent local-clock boundaries."""
    start, end = utc(start), utc(end)
    zone = ZoneInfo(timezone)
    day = start.astimezone(zone).date() - timedelta(days=1)
    last = end.astimezone(zone).date() + timedelta(days=1)
    result = set()
    while day <= last:
        for minute in minutes:
            wall = datetime.combine(day, time()) + timedelta(minutes=minute)
            for fold in (0, 1):
                instant = wall.replace(tzinfo=zone, fold=fold).astimezone(UTC)
                if (
                    instant.astimezone(zone).replace(tzinfo=None) == wall
                    and start < instant < end
                ):
                    result.add(instant)
        day += timedelta(days=1)
    # A clock jump itself can change the active tariff or local date.
    left = start
    while left < end:
        right = min(left + timedelta(hours=1), end)
        offset = left.astimezone(zone).utcoffset()
        if offset != right.astimezone(zone).utcoffset():
            low, high = left, right
            while high - low > timedelta(microseconds=1):
                middle = low + (high - low) // 2
                if middle.astimezone(zone).utcoffset() == offset:
                    low = middle
                else:
                    high = middle
            changes_date = (high - timedelta(microseconds=1)).astimezone(
                zone
            ).date() != high.astimezone(zone).date()
            if start < high < end and (clock_changes or changes_date):
                result.add(high)
        left = right
    return sorted(result)


def _minute(value: str, *, end: bool = False) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError("Time must be HH:MM")
    hour, minute = map(int, value.split(":"))
    if end and hour == 24 and minute == 0:
        return 1440
    if hour > 23 or minute > 59:
        raise ValueError("Invalid time")
    return hour * 60 + minute


class DailySchedule:
    def __init__(self, rows: list[dict[str, str]]):
        intervals = []
        for row in rows:
            try:
                left, right = _minute(row["start"]), _minute(row["end"], end=True)
                price = decimal_value(row["price"])
            except (KeyError, TypeError) as err:
                raise ValueError("Invalid tariff row") from err
            if left == right:
                raise ValueError("Empty tariff interval")
            if right < left:
                intervals.extend([(left, 1440, price), (0, right, price)])
            else:
                intervals.append((left, right, price))
        intervals = sorted(
            interval for interval in intervals if interval[0] != interval[1]
        )
        cursor = 0
        for left, right, _ in intervals:
            if left != cursor:
                raise ValueError("Tariffs must cover the day without overlap")
            cursor = right
        if cursor != 1440:
            raise ValueError("Tariffs must cover the entire day")
        self._intervals = intervals

    def price_at(self, at: datetime, timezone: str) -> Decimal:
        local = utc(at).astimezone(ZoneInfo(timezone))
        minute = local.hour * 60 + local.minute
        return next(
            price for left, right, price in self._intervals if left <= minute < right
        )

    def boundaries(
        self, start: datetime, end: datetime, timezone: str
    ) -> list[datetime]:
        if utc(end) <= utc(start):
            raise ValueError("End must follow start")
        return calendar_boundaries(
            start,
            end,
            timezone,
            {left for left, _, _ in self._intervals},
            clock_changes=True,
        )
