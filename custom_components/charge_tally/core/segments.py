"""Conserving energy allocation across UTC and local calendar boundaries."""
from datetime import datetime
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from .tariffs import calendar_boundaries, elapsed, utc
from .units import decimal_value


def split_interval(start: datetime, end: datetime, energy: Decimal, timezone: str,
                   prices: list[tuple[datetime, Decimal | None]],
                   extra_boundaries: list[datetime] | None = None) -> list[dict]:
    start, end = utc(start), utc(end)
    energy = decimal_value(energy, nonnegative=True)
    if end <= start:
        raise ValueError('End must follow start')
    zone = ZoneInfo(timezone)
    timeline = []
    for instant, value in prices:
        instant = utc(instant)
        value = None if value is None else decimal_value(value)
        if timeline and instant < timeline[-1][0]:
            raise ValueError('Price timeline is out of order')
        if timeline and instant == timeline[-1][0]:
            if value != timeline[-1][1]:
                raise ValueError('Conflicting prices at the same instant')
            continue
        timeline.append((instant, value))
    cuts = {start, end, *calendar_boundaries(start, end, timezone, {0})}
    cuts.update(at for at, _ in timeline if start < at < end)
    cuts.update(at for at in map(utc, extra_boundaries or []) if start < at < end)
    cuts = sorted(cuts)
    result = []
    price_index, price = 0, None
    with localcontext() as ctx:
        ctx.prec = 36
        allocated = Decimal(0)
        for index, (left, right) in enumerate(zip(cuts, cuts[1:])):
            while price_index < len(timeline) and timeline[price_index][0] <= left:
                price = timeline[price_index][1]
                price_index += 1
            cumulative = energy if index == len(cuts) - 2 else energy * elapsed(start, right) / elapsed(start, end)
            portion = cumulative - allocated
            allocated = cumulative
            result.append({'start': left.isoformat(), 'end': right.isoformat(),
                           'energy_kwh': str(portion), 'cost': None if price is None else str(portion * price),
                           'local_date': left.astimezone(zone).date().isoformat(),
                           'quality': ['price_unknown'] if price is None else []})
    return result
