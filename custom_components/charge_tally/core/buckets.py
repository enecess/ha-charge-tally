"""Stable local-calendar windows for period-sensitive statistics."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .tariffs import calendar_boundaries, utc

PERIODS = ('hour', 'day', 'month', 'year')


def choose_bucket_period(requested: str, *, calendar: str | None,
                         start: datetime | None, end: datetime | None, timezone: str) -> str:
    if requested not in ('auto', *PERIODS):
        raise ValueError('Invalid bucket period')
    if requested != 'auto':
        return requested
    if calendar is not None:
        try:
            return {10: 'hour', 7: 'day', 4: 'month'}[len(calendar)]
        except KeyError:
            raise ValueError('Invalid calendar label') from None
    if start is None and end is None:
        return 'year'
    if start is None or end is None or utc(end) <= utc(start):
        raise ValueError('A complete increasing range is required')
    zone = ZoneInfo(timezone)
    days = (utc(end).astimezone(zone).date() - utc(start).astimezone(zone).date()).days
    return 'hour' if days <= 2 else 'day' if days <= 90 else 'month' if days <= 730 else 'year'


@dataclass(frozen=True)
class BucketWindow:
    key: str
    label: str
    start: datetime
    end: datetime
    timezone: str


def bucket_windows(start: datetime, end: datetime, timezone: str, period: str) -> list[BucketWindow]:
    start, end = utc(start), utc(end)
    if period not in PERIODS or end <= start:
        raise ValueError('Invalid bucket window')
    zone = ZoneInfo(timezone)
    try:
        if period == 'hour':
            # Surround samples so a partial hour always receives its complete window.
            boundaries = calendar_boundaries(start-timedelta(days=2), end+timedelta(days=2),
                                              timezone, set(range(0, 1440, 60)), clock_changes=True)
        else:
            local = start.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
            if period in ('month', 'year'):
                local = local.replace(day=1)
            if period == 'year':
                local = local.replace(month=1)
            boundaries = [utc(local)]
            while boundaries[-1] < end:
                if period == 'day':
                    local += timedelta(days=1)
                elif period == 'month':
                    local = local.replace(year=local.year+(local.month == 12), month=local.month % 12+1)
                else:
                    local = local.replace(year=local.year+1)
                boundaries.append(utc(local))
        windows = []
        for left, right in zip(boundaries, boundaries[1:]):
            if left >= end or right <= start or right <= left:
                continue
            local = left.astimezone(zone)
            label = local.isoformat(timespec='minutes') if period == 'hour' else local.strftime({'day': '%Y-%m-%d', 'month': '%Y-%m', 'year': '%Y'}[period])
            key = f'{timezone}:{left.isoformat()}' if period == 'hour' else label
            windows.append(BucketWindow(key, label, left, right, timezone))
        return windows
    except (OverflowError, OSError) as err:
        raise ValueError('Bucket range is outside supported dates') from err
