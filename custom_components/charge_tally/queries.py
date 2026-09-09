"""Read current record revisions, independent of Home Assistant Recorder."""
from decimal import Decimal, localcontext

from .accounting import instant
from .core.segments import split_interval
from .core.tariffs import elapsed


def summarize(ledger, start, end, identity_id=None, point_id=None):
    start, end = instant(start) if start else None, instant(end) if end else None
    if start and end and end <= start:
        raise ValueError('Query end must follow start')
    result = dict(energy_kwh='0', known_cost='0', cost_complete=True, active_count=0, completed_count=0, quality=[], buckets=[])
    energy, cost, quality, buckets = Decimal(0), Decimal(0), set(), {}

    def daily(date):
        return buckets.setdefault(date, dict(local_date=date, energy=Decimal(0), cost=Decimal(0), cost_complete=True, quality=set()))

    with ledger.transaction(), localcontext() as ctx:
        ctx.prec = 36
        for record in ledger.list_records(point_id, identity_id):
            begins = instant(record['start'])
            finishes = instant(record['end']) if record['end'] else None
            if (end and begins >= end) or (start and finishes and finishes <= start):
                continue
            if record['status'] == 'active':
                result['active_count'] += 1
            elif (start is None or begins >= start) and (end is None or begins < end):
                result['completed_count'] += 1
            if record['status'] == 'active':
                quality.add('provisional')
            for span in record.get('quality_spans', []):
                a = max(instant(span['start']), start) if start else instant(span['start'])
                b = min(instant(span['end']), end) if end else instant(span['end'])
                if a < b:
                    quality.update(span['quality'])
                    result['cost_complete'] = False
                    for part in split_interval(a, b, Decimal(0), record['timezone'], []):
                        bucket = daily(part['local_date'])
                        bucket['cost_complete'] = False
                        bucket['quality'].update(span['quality'])
                        if record['status'] == 'active':
                            bucket['quality'].add('provisional')
            for part in ledger.list_segments(record['id']):
                left, right = instant(part['start']), instant(part['end'])
                a, b = max(left, start) if start else left, min(right, end) if end else right
                if b <= a:
                    continue
                weight = elapsed(a, b) / elapsed(left, right)
                amount = Decimal(part['energy_kwh']) * weight
                fee = Decimal(part['cost']) * weight if part['cost'] is not None else Decimal(0)
                marks = set(part['quality'])
                if record['status'] == 'active':
                    marks.add('provisional')
                if a != left or b != right:
                    marks.add('estimated')
                if part['cost'] is None:
                    marks.add('missing_price')
                    result['cost_complete'] = False
                marks.discard('price_unknown')
                quality.update(marks)
                energy += amount
                cost += fee
                bucket = daily(part['local_date'])
                bucket['energy'] += amount
                bucket['cost'] += fee
                bucket['cost_complete'] &= part['cost'] is not None
                bucket['quality'].update(marks)
    result.update(energy_kwh=str(energy), known_cost=str(cost), quality=sorted(quality),
                  buckets=[dict(local_date=key, energy_kwh=str(b['energy']), known_cost=str(b['cost']), cost_complete=b['cost_complete'], quality=sorted(b['quality'])) for key, b in sorted(buckets.items())])
    return result
