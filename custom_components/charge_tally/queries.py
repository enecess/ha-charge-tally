"""Read current record revisions, independent of Home Assistant Recorder."""
from decimal import Decimal, localcontext
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .accounting import instant
from .core.buckets import bucket_windows, choose_bucket_period
from .core.tariffs import elapsed


def calendar_bounds(label, timezone):
    """Interpret a calendar label in the original record's accounting timezone."""
    if len(label) not in (4, 7, 10):
        raise ValueError('Invalid calendar label')
    value = label + {4: '-01-01', 7: '-01', 10: ''}[len(label)]
    start = datetime.strptime(value, '%Y-%m-%d').replace(tzinfo=ZoneInfo(timezone))
    if start.strftime('%Y-%m-%d') != value:
        raise ValueError('Invalid calendar label')
    if len(label) == 4:
        end = start.replace(year=start.year + 1)
    elif len(label) == 7:
        end = start.replace(year=start.year + (start.month == 12), month=start.month % 12 + 1)
    else:
        end = start + timedelta(days=1)
    return instant(start), instant(end)


def summarize(ledger, start, end, identity_id=None, point_id=None, *, calendar=None,
              bucket_period='auto', timezone='UTC'):
    if calendar is not None and (start is not None or end is not None):
        raise ValueError('Calendar and absolute range are mutually exclusive')
    start, end = instant(start) if start else None, instant(end) if end else None
    if calendar is not None:
        calendar_bounds(calendar, 'UTC')
    if start and end and end <= start:
        raise ValueError('Query end must follow start')
    period = choose_bucket_period(bucket_period, calendar=calendar, start=start, end=end, timezone=timezone)
    absolute_start, absolute_end = start, end
    result = dict(energy_kwh='0', known_cost='0', cost_complete=True, active_count=0,
                  completed_count=0, matched_count=0, has_energy_data=False, has_known_cost=False,
                  bucket_period=period, quality=[], buckets=[])
    energy, cost, quality, buckets = Decimal(0), Decimal(0), set(), {}
    hourly_windows = {}

    def windows_for(a, b, record_timezone):
        if period != 'hour':
            return bucket_windows(a, b, record_timezone, period)
        # Cache full UTC-date spans only for this query. Window boundaries still
        # use the record's local calendar, including folds and clock changes.
        left = a.replace(hour=0, minute=0, second=0, microsecond=0)
        right = (b-timedelta(microseconds=1)).replace(hour=0, minute=0, second=0, microsecond=0)+timedelta(days=1)
        key = (record_timezone, left, right)
        if key not in hourly_windows:
            hourly_windows[key] = bucket_windows(left, right, record_timezone, period)
        return [window for window in hourly_windows[key] if window.start < b and window.end > a]

    def bucket(window):
        if window.key not in buckets:
            item = dict(key=window.key, label=window.label, energy=Decimal(0), cost=Decimal(0),
                        cost_complete=True, quality=set(), has_energy_data=False, has_known_cost=False)
            if period == 'hour':
                item.update(start=window.start.isoformat(), end=window.end.isoformat(), timezone=window.timezone)
            buckets[window.key] = item
        return buckets[window.key]

    with ledger.transaction(), localcontext() as ctx:
        ctx.prec = 36
        for record in ledger.list_records(point_id, identity_id):
            start, end = calendar_bounds(calendar, record['timezone']) if calendar is not None else (absolute_start, absolute_end)
            begins = instant(record['start'])
            finishes = instant(record['end']) if record['end'] else None
            if (end and begins >= end) or (start and finishes and finishes <= start):
                continue
            result['matched_count'] += 1
            active = record['status'] == 'active'
            if active:
                result['active_count'] += 1
                quality.add('provisional')
            elif (start is None or begins >= start) and (end is None or begins < end):
                result['completed_count'] += 1
            for span in record.get('quality_spans', []):
                a = max(instant(span['start']), start) if start else instant(span['start'])
                b = min(instant(span['end']), end) if end else instant(span['end'])
                if a >= b:
                    continue
                quality.update(span['quality'])
                result['cost_complete'] = False
                for window in windows_for(a, b, record['timezone']):
                    item = bucket(window)
                    item['cost_complete'] = False
                    item['quality'].update(span['quality'])
                    if active:
                        item['quality'].add('provisional')
            # Raw ledger segments preserve the actual sample distribution.
            for part in ledger.list_segments(record['id']):
                left, right = instant(part['start']), instant(part['end'])
                a, b = max(left, start) if start else left, min(right, end) if end else right
                if b <= a:
                    continue
                weight = elapsed(a, b) / elapsed(left, right)
                amount = Decimal(part['energy_kwh']) * weight
                fee = Decimal(part['cost']) * weight if part['cost'] is not None else None
                windows = windows_for(a, b, record['timezone'])
                marks = set(part['quality'])
                if active:
                    marks.add('provisional')
                if a != left or b != right or len(windows) > 1:
                    marks.add('estimated')
                if fee is None:
                    marks.add('missing_price')
                    result['cost_complete'] = False
                marks.discard('price_unknown')
                quality.update(marks)
                energy += amount
                cost += fee if fee is not None else Decimal(0)
                result['has_energy_data'] = True
                result['has_known_cost'] |= fee is not None
                allocated_energy, allocated_cost = Decimal(0), Decimal(0)
                for index, window in enumerate(windows):
                    item = bucket(window)
                    fraction = elapsed(a, min(b, window.end)) / elapsed(a, b)
                    cumulative_energy = amount if index == len(windows)-1 else amount * fraction
                    item['energy'] += cumulative_energy - allocated_energy
                    allocated_energy = cumulative_energy
                    if fee is not None:
                        cumulative_cost = fee if index == len(windows)-1 else fee * fraction
                        item['cost'] += cumulative_cost - allocated_cost
                        allocated_cost = cumulative_cost
                    item['has_energy_data'] = True
                    item['has_known_cost'] |= fee is not None
                    item['cost_complete'] &= fee is not None
                    item['quality'].update(marks)
    ordered = sorted(buckets.values(), key=lambda item: (item.get('start', item['key']), item['key']))
    # Match the selected totals despite Decimal addition being non-associative.
    # Keep true-zero and unknown buckets unchanged; the last nonzero bucket owns
    # the aggregate remainder, after summing its predecessors in public order.
    with localcontext() as ctx:
        ctx.prec = 36
        for field, total in (('energy', energy), ('cost', cost)):
            last = next((index for index in range(len(ordered)-1, -1, -1)
                         if ordered[index][field] != 0), None)
            if last is None:
                continue
            prefix = sum((item[field] for item in ordered[:last]), Decimal(0))
            # Subtract exactly, including cancellation between differently sized
            # values; adding this remainder to the prefix rounds back to total.
            with localcontext() as exact:
                exact.prec = max(total.adjusted(), prefix.adjusted()) - min(
                    total.as_tuple().exponent, prefix.as_tuple().exponent) + 2
                ordered[last][field] = total - prefix
    result.update(energy_kwh=str(energy), known_cost=str(cost), quality=sorted(quality),
                  buckets=[{**{k: v for k, v in item.items() if k not in ('energy', 'cost', 'quality')},
                            'energy_kwh': str(item['energy']), 'known_cost': str(item['cost']),
                            'quality': sorted(item['quality'])} for item in ordered])
    return result
