"""Transactional SQLite ledger, owned by one serial worker thread."""
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from pathlib import Path

from .config_validation import identity_name_key


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def retained_currency(path):
    """Inspect a retained ledger without creating or changing it."""
    if not Path(path).exists():
        return None
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT data FROM checkpoints WHERE id='_currency'").fetchone()
        if row:
            return json.loads(row[0])
        if any(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in ('points', 'records', 'price_versions', 'observations')):
            raise ValueError('currency_unbound')
    return None


class Ledger:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.execute('PRAGMA foreign_keys=ON')
        version = self._db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            self._db.close()
            raise ValueError('Unsupported ledger schema version')
        with self.transaction():
            for table in ('identities', 'points', 'observations', 'price_versions', 'requests', 'checkpoints', 'previews', 'observation_resolutions'):
                self._db.execute(f'CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            self._db.execute("CREATE INDEX IF NOT EXISTS observation_time ON observations(json_extract(data,'$.point_id'),json_extract(data,'$.start'),json_extract(data,'$.end'))")
            self._db.execute("CREATE INDEX IF NOT EXISTS price_time ON price_versions(json_extract(data,'$.point_id'),json_extract(data,'$.at'))")
            self._db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, point_id TEXT NOT NULL REFERENCES points(id), identity_id TEXT NOT NULL REFERENCES identities(id), start TEXT NOT NULL, end TEXT, status TEXT NOT NULL, data TEXT NOT NULL)')
            self._db.execute('CREATE INDEX IF NOT EXISTS record_time ON records(point_id,start,end)')
            self._db.execute('CREATE TABLE IF NOT EXISTS segments (record_id TEXT NOT NULL REFERENCES records(id), position INTEGER NOT NULL, observation_id TEXT REFERENCES observations(id), data TEXT NOT NULL, PRIMARY KEY(record_id,position))')
            self._db.execute('CREATE TABLE IF NOT EXISTS revisions (record_id TEXT NOT NULL REFERENCES records(id), revision INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(record_id,revision))')
            self._db.execute('PRAGMA user_version=1')

    @property
    def currency(self):
        return self.get_checkpoint('_currency')

    def bind_currency(self, currency, *, confirm_existing=False):
        """Bind once; pre-release data requires an explicit, backed-up confirmation."""
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isalpha() or currency != currency.upper():
            raise ValueError('invalid_currency')
        with self.transaction():
            if self.currency is not None:
                if self.currency != currency:
                    raise ValueError('currency_mismatch')
                return
            populated = any(self._db.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone()
                            for table in ('points', 'records', 'price_versions', 'observations'))
            if populated and not confirm_existing:
                raise ValueError('currency_unbound')
            self._put('checkpoints', '_currency', currency)

    @contextmanager
    def transaction(self):
        nested = self._db.in_transaction
        name = f'sp_{id(object())}'
        self._db.execute(f'SAVEPOINT {name}' if nested else 'BEGIN IMMEDIATE')
        try:
            yield self
        except BaseException:
            self._db.execute(f'ROLLBACK TO {name}' if nested else 'ROLLBACK')
            if nested:
                self._db.execute(f'RELEASE {name}')
            raise
        else:
            self._db.execute(f'RELEASE {name}' if nested else 'COMMIT')

    def close(self):
        self._db.close()

    def backup(self, path: str):
        if self._db.in_transaction:
            raise ValueError('Backup requires a committed ledger')
        with closing(sqlite3.connect(path)) as target:
            self._db.backup(target)

    def _get(self, table, key):
        row = self._db.execute(f'SELECT data FROM {table} WHERE id=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _list(self, table):
        return [json.loads(row[0]) for row in self._db.execute(f'SELECT data FROM {table} ORDER BY id')]

    def _put(self, table, key, data):
        if not isinstance(key, str) or not key:
            raise ValueError('A nonempty stable ID is required')
        self._db.execute(f'INSERT INTO {table}(id,data) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', (key, encode(data)))

    def data_version(self):
        return self.get_checkpoint('_data_version') or 0

    def _bump(self):
        self._put('checkpoints', '_data_version', self.data_version() + 1)

    def put_identity(self, data: dict):
        with self.transaction():
            if data.get('active', True) and any(item.get('active', True) and identity_name_key(item.get('name')) == identity_name_key(data.get('name')) and item['id'] != data['id'] for item in self.list_identities()):
                raise ValueError('Identity name must be unique')
            self._put('identities', data['id'], data)
            self._bump()

    def put_point(self, data: dict):
        with self.transaction():
            self._put('points', data['id'], data)
            self._bump()

    def get_identity(self, id: str):
        return self._get('identities', id)

    def get_point(self, id: str):
        return self._get('points', id)

    def list_identities(self):
        return self._list('identities')

    def list_points(self):
        return self._list('points')

    def put_checkpoint(self, key: str, data):
        if key.startswith('_'):
            raise ValueError('Reserved checkpoint key')
        with self.transaction():
            self._put('checkpoints', key, data)

    def get_checkpoint(self, key: str):
        return self._get('checkpoints', key)

    def put_price_version(self, data: dict):
        from .core.tariffs import utc
        data = dict(data)
        data['at'] = utc(datetime.fromisoformat(data['at'])).isoformat()
        with self.transaction():
            if not self.get_point(data['point_id']):
                raise ValueError('Unknown point')
            prior = self._get('price_versions', data['id'])
            if prior is not None and prior != data:
                raise ValueError('Price versions are immutable')
            if prior is None:
                self._put('price_versions', data['id'], data)
                self._bump()

    def list_price_versions(self, point_id: str):
        return sorted((p for p in self._list('price_versions') if p['point_id'] == point_id), key=lambda p: p['at'])

    def put_interval(self, data: dict):
        with self.transaction():
            prior = self._get('observations', data['id'])
            if prior is not None:
                if prior != data:
                    raise ValueError('Interval ID conflicts with immutable data')
                return False
            if not self.get_point(data['point_id']):
                raise ValueError('Unknown point')
            if any(p['start'] < data['end'] and p['end'] > data['start'] for p in self.list_intervals(data['point_id'])):
                raise ValueError('Meter intervals must not overlap')
            self._put('observations', data['id'], data)
            self._bump()
            return True

    def list_intervals(self, point_id: str, start=None, end=None, include_superseded=False):
        rows = self._db.execute("SELECT data FROM observations WHERE json_extract(data,'$.point_id')=? AND (? IS NULL OR json_extract(data,'$.end')>?) AND (? IS NULL OR json_extract(data,'$.start')<?) AND (? OR id NOT IN (SELECT id FROM observation_resolutions)) ORDER BY json_extract(data,'$.start')", (point_id, start, start, end, end, include_superseded))
        return [json.loads(row[0]) for row in rows]

    def resolve_gap(self, gap_id: str, intervals: list[dict]):
        from decimal import Decimal, localcontext
        with self.transaction():
            gap = self._get('observations', gap_id)
            if not gap or not gap.get('gap') or self._get('observation_resolutions', gap_id):
                raise ValueError('Unresolved source gap required')
            cursor = gap['start']
            for item in intervals:
                if item['point_id'] != gap['point_id'] or item['start'] != cursor or item['end'] <= cursor or item.get('gap'):
                    raise ValueError('Replacement history must continuously cover the gap')
                cursor = item['end']
            with localcontext() as ctx:
                ctx.prec = 36
                energy = sum((Decimal(i['energy_kwh']) for i in intervals), Decimal(0))
            if cursor != gap['end'] or energy != Decimal(gap['energy_kwh']):
                raise ValueError('Replacement history must conserve source gap energy and bounds')
            self._put('observation_resolutions', gap_id, {'interval_ids': [i['id'] for i in intervals]})
            for item in intervals:
                self.put_interval(item)
            self._bump()

    def get_record(self, id: str):
        return self._get('records', id)

    def list_records(self, point_id=None, identity_id=None, include_void=False):
        return sorted((r for r in self._list('records') if (point_id is None or r['point_id'] == point_id) and (identity_id is None or r['identity_id'] == identity_id) and (include_void or r['status'] != 'void')), key=lambda r: (r['start'], r['id']))

    def overlaps(self, point_id, start, end, exclude_id=''):
        rows = self._db.execute("SELECT id FROM records WHERE point_id=? AND status!='void' AND id!=? AND start<COALESCE(?, '9999-12-31T23:59:59+00:00') AND (end IS NULL OR end>?) ORDER BY start,id", (point_id, exclude_id, end, start))
        return [r[0] for r in rows]

    def save_record(self, record: dict, segments: list[dict]):
        with self.transaction():
            if record['status'] != 'void' and self.overlaps(record['point_id'], record['start'], record['end'], record['id']):
                raise ValueError('Record interval overlaps an existing record')
            self._db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET point_id=excluded.point_id,identity_id=excluded.identity_id,start=excluded.start,end=excluded.end,status=excluded.status,data=excluded.data', (record['id'], record['point_id'], record['identity_id'], record['start'], record['end'], record['status'], encode(record)))
            self._db.execute('DELETE FROM segments WHERE record_id=?', (record['id'],))
            for index, segment in enumerate(segments):
                self._db.execute('INSERT INTO segments VALUES (?,?,?,?)', (record['id'], index, segment.get('observation_id'), encode(segment)))
            self._db.execute('INSERT INTO revisions VALUES (?,?,?)', (record['id'], record['revision'], encode({'record': record, 'segments': segments})))
            self._bump()

    def list_segments(self, record_id: str):
        return [json.loads(r[0]) for r in self._db.execute('SELECT data FROM segments WHERE record_id=? ORDER BY position', (record_id,))]

    def list_revisions(self, record_id: str):
        return [json.loads(r[0]) for r in self._db.execute('SELECT data FROM revisions WHERE record_id=? ORDER BY revision', (record_id,))]

    def get_request(self, request_id: str):
        return self._get('requests', request_id)

    def put_request(self, request_id: str, data: dict):
        with self.transaction():
            if self.get_request(request_id) is not None:
                raise ValueError('Request already exists')
            self._put('requests', request_id, data)

    def put_preview(self, token: str, data: dict):
        with self.transaction():
            self._put('previews', token, data)

    def get_preview(self, token: str):
        return self._get('previews', token)

    def prune(self, before: datetime | None = None, limit: int = 500):
        from .core.tariffs import utc
        cutoff = utc(before or datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        removed = 0
        with self.transaction():
            revision_references = set()
            retained_ranges = {}
            for row in self._db.execute('SELECT data FROM revisions'):
                revision = json.loads(row[0])
                revision_references.update(s.get('observation_id') for s in revision['segments'])
                record = revision['record']
                if record['end']:
                    retained_ranges.setdefault(record['point_id'], []).append((record['start'], record['end']))
            for record in self.list_records():
                if record['status'] == 'active':
                    retained_ranges.setdefault(record['point_id'], []).append((record['start'], None))
            for item in self._list('observations'):
                if removed >= limit:
                    break
                referenced = self._db.execute('SELECT 1 FROM segments WHERE observation_id=? LIMIT 1', (item['id'],)).fetchone()
                if item['end'] < cutoff and not referenced and item['id'] not in revision_references and not item.get('gap') and not self.overlaps(item['point_id'], item['start'], item['end']):
                    self._db.execute('DELETE FROM observations WHERE id=?', (item['id'],))
                    removed += 1
            for point in self.list_points():
                ranges = retained_ranges.get(point['id'], []) + [(i['start'], i['end']) for i in self.list_intervals(point['id'], include_superseded=True)]
                prices = self.list_price_versions(point['id'])
                old_prices = [p for p in prices if p['at'] < cutoff]
                anchor = old_prices[-1]['id'] if old_prices else None
                pruned = self.get_checkpoint('_price_gaps:' + point['id']) or []
                for index, price in enumerate(prices):
                    if removed >= limit:
                        break
                    right = prices[index + 1]['at'] if index + 1 < len(prices) else None
                    referenced = any((end is None or price['at'] < end) and (right is None or right > start) for start, end in ranges)
                    if price['at'] >= cutoff or price['id'] == anchor or referenced:
                        continue
                    self._db.execute('DELETE FROM price_versions WHERE id=?', (price['id'],))
                    pruned.append({'start': price['at'], 'end': right})
                    removed += 1
                if pruned:
                    merged = []
                    for span in sorted(pruned, key=lambda s: s['start']):
                        if merged and merged[-1]['end'] == span['start']:
                            merged[-1]['end'] = span['end']
                        else:
                            merged.append(span)
                    self._put('checkpoints', '_price_gaps:' + point['id'], merged)
            if removed:
                self._bump()
        return removed
