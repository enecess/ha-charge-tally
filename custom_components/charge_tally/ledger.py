"""Transactional SQLite ledger, owned by one serial worker thread."""

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from .config_validation import identity_name_key
from .const import PREVIEW_LIFETIME_SECONDS

SCHEMA_VERSION = 2


def _schema_version(db):
    """Reject unsupported files before any application reads or writes."""
    version = db.execute("PRAGMA user_version").fetchone()[0]
    has_tables = (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
        ).fetchone()
        is not None
    )
    if version != SCHEMA_VERSION and not (version == 0 and not has_tables):
        raise ValueError("Unsupported ledger schema version")
    return version


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def retained_currency(path):
    """Inspect a retained ledger without creating or changing it."""
    if not Path(path).exists():
        return None
    with closing(
        sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    ) as db:
        if _schema_version(db) == 0:
            return None
        row = db.execute("SELECT data FROM checkpoints WHERE id='_currency'").fetchone()
        if row:
            return json.loads(row[0])
        if any(
            db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
            for table in ("points", "records", "price_versions", "observations")
        ):
            raise ValueError("currency_unbound")
    return None


class Ledger:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.execute("PRAGMA foreign_keys=ON")
        try:
            _schema_version(self._db)
        except Exception:
            self._db.close()
            raise
        with self.transaction():
            for table in (
                "identities",
                "points",
                "observations",
                "price_versions",
                "requests",
                "checkpoints",
                "previews",
                "observation_resolutions",
            ):
                self._db.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
                )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS observation_time ON observations(json_extract(data,'$.point_id'),json_extract(data,'$.start'),json_extract(data,'$.end'))"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS observation_end ON observations(json_extract(data,'$.end'),id)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS price_time ON price_versions(json_extract(data,'$.point_id'),json_extract(data,'$.at'))"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS price_age ON price_versions(json_extract(data,'$.at'),id)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS preview_expiry ON previews(COALESCE(json_extract(data,'$.created_at'),''),id) WHERE json_extract(data,'$.consumed') IS NOT 1"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS request_digest ON requests(json_extract(data,'$.digest'))"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, point_id TEXT NOT NULL REFERENCES points(id), identity_id TEXT NOT NULL REFERENCES identities(id), start TEXT NOT NULL, end TEXT, status TEXT NOT NULL, data TEXT NOT NULL)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS record_time ON records(point_id,start,end)"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS segments (record_id TEXT NOT NULL REFERENCES records(id), position INTEGER NOT NULL, observation_id TEXT REFERENCES observations(id), data TEXT NOT NULL, PRIMARY KEY(record_id,position))"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS segment_observation ON segments(observation_id)"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS revisions (record_id TEXT NOT NULL REFERENCES records(id), revision INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(record_id,revision))"
            )
            self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @property
    def currency(self):
        return self.get_checkpoint("_currency")

    def bind_currency(self, currency):
        """Bind an empty ledger without relabeling existing accounting data."""
        if (
            not isinstance(currency, str)
            or len(currency) != 3
            or not currency.isascii()
            or not currency.isalpha()
            or currency != currency.upper()
        ):
            raise ValueError("invalid_currency")
        with self.transaction():
            if self.currency is not None:
                if self.currency != currency:
                    raise ValueError("currency_mismatch")
                return
            populated = any(
                self._db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                for table in ("points", "records", "price_versions", "observations")
            )
            if populated:
                raise ValueError("currency_unbound")
            self._put("checkpoints", "_currency", currency)

    def currency_change_allowed(self):
        """Keep archived and pending accounting evidence in its original currency."""
        populated = any(
            self._db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
            for table in (
                "points",
                "records",
                "price_versions",
                "observations",
                "segments",
                "revisions",
                "previews",
                "requests",
            )
        )
        return not populated

    def change_currency(self, currency, expected_currency):
        """Rebind an empty ledger, checking its state in the same transaction."""
        with self.transaction():
            if self.currency != expected_currency:
                raise ValueError("config_changed")
            if not self.currency_change_allowed():
                raise ValueError("currency_locked")
            if (
                not isinstance(currency, str)
                or len(currency) != 3
                or not currency.isascii()
                or not currency.isalpha()
                or currency != currency.upper()
            ):
                raise ValueError("invalid_currency")
            self._put("checkpoints", "_currency", currency)

    @contextmanager
    def transaction(self):
        nested = self._db.in_transaction
        name = f"sp_{id(object())}"
        self._db.execute(f"SAVEPOINT {name}" if nested else "BEGIN IMMEDIATE")
        try:
            yield self
            self._db.execute(f"RELEASE {name}" if nested else "COMMIT")
        except BaseException:
            self._db.execute(f"ROLLBACK TO {name}" if nested else "ROLLBACK")
            if nested:
                self._db.execute(f"RELEASE {name}")
            raise

    def close(self):
        self._db.close()

    def backup(self, path: str):
        if self._db.in_transaction:
            raise ValueError("Backup requires a committed ledger")
        with closing(sqlite3.connect(path)) as target:
            self._db.backup(target)

    def _get(self, table, key):
        row = self._db.execute(
            f"SELECT data FROM {table} WHERE id=?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def _list(self, table):
        return [
            json.loads(row[0])
            for row in self._db.execute(f"SELECT data FROM {table} ORDER BY id")
        ]

    def _put(self, table, key, data):
        if not isinstance(key, str) or not key:
            raise ValueError("A nonempty stable ID is required")
        self._db.execute(
            f"INSERT INTO {table}(id,data) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (key, encode(data)),
        )

    def data_version(self):
        return self.get_checkpoint("_data_version") or 0

    def _bump(self):
        self._put("checkpoints", "_data_version", self.data_version() + 1)

    def put_identity(self, data: dict):
        with self.transaction():
            if data.get("active", True) and any(
                item.get("active", True)
                and identity_name_key(item.get("name"))
                == identity_name_key(data.get("name"))
                and item["id"] != data["id"]
                for item in self.list_identities()
            ):
                raise ValueError("Identity name must be unique")
            self._put("identities", data["id"], data)
            self._bump()

    def put_point(self, data: dict):
        with self.transaction():
            self._put("points", data["id"], data)
            self._bump()

    def get_identity(self, id: str):
        return self._get("identities", id)

    def get_point(self, id: str):
        return self._get("points", id)

    def list_identities(self):
        return self._list("identities")

    def list_points(self):
        return self._list("points")

    def put_checkpoint(self, key: str, data):
        if key.startswith("_"):
            raise ValueError("Reserved checkpoint key")
        with self.transaction():
            self._put("checkpoints", key, data)

    def get_checkpoint(self, key: str):
        return self._get("checkpoints", key)

    def put_price_version(self, data: dict):
        from .core.tariffs import utc

        data = dict(data)
        data["at"] = utc(datetime.fromisoformat(data["at"])).isoformat()
        with self.transaction():
            if not self.get_point(data["point_id"]):
                raise ValueError("Unknown point")
            prior = self._get("price_versions", data["id"])
            if prior is not None and prior != data:
                raise ValueError("Price versions are immutable")
            if prior is None:
                self._put("price_versions", data["id"], data)
                self._bump()

    def list_price_versions(self, point_id: str, start=None, end=None):
        clauses, parameters = ["json_extract(data,'$.point_id')=?"], [point_id]
        if start is not None:
            anchor = self._db.execute(
                "SELECT json_extract(data,'$.at'),id FROM price_versions "
                "WHERE json_extract(data,'$.point_id')=? AND json_extract(data,'$.at')<=? "
                "ORDER BY json_extract(data,'$.at') DESC,id DESC LIMIT 1",
                (point_id, start),
            ).fetchone()
            if anchor:
                # SQLite needs the scalar bound to seek before the ID tie-break.
                clauses.append(
                    "json_extract(data,'$.at')>=? AND (json_extract(data,'$.at'),id)>=(?,?)"
                )
                parameters.extend([anchor[0], *anchor])
        if end is not None:
            clauses.append("json_extract(data,'$.at')<?")
            parameters.append(end)
        return [
            json.loads(row[0])
            for row in self._db.execute(
                "SELECT data FROM price_versions WHERE "
                + " AND ".join(clauses)
                + " ORDER BY json_extract(data,'$.at'),id",
                parameters,
            )
        ]

    def put_interval(self, data: dict):
        with self.transaction():
            prior = self._get("observations", data["id"])
            if prior is not None:
                if prior != data:
                    raise ValueError("Interval ID conflicts with immutable data")
                return False
            if not self.get_point(data["point_id"]):
                raise ValueError("Unknown point")
            overlap = self._db.execute(
                "SELECT EXISTS(SELECT 1 FROM observations INDEXED BY observation_end WHERE json_extract(data,'$.point_id')=? "
                "AND json_extract(data,'$.start')<? AND json_extract(data,'$.end')>? "
                "AND id NOT IN (SELECT id FROM observation_resolutions))",
                (data["point_id"], data["end"], data["start"]),
            ).fetchone()[0]
            if overlap:
                raise ValueError("Meter intervals must not overlap")
            self._put("observations", data["id"], data)
            self._bump()
            return True

    def list_intervals(
        self, point_id: str, start=None, end=None, include_superseded=False
    ):
        clauses, parameters = ["json_extract(data,'$.point_id')=?"], [point_id]
        if start is not None:
            clauses.append("json_extract(data,'$.end')>?")
            parameters.append(start)
        if end is not None:
            clauses.append("json_extract(data,'$.start')<?")
            parameters.append(end)
        if not include_superseded:
            clauses.append("id NOT IN (SELECT id FROM observation_resolutions)")
        index = "observation_end" if start is not None else "observation_time"
        rows = self._db.execute(
            f"SELECT data FROM observations INDEXED BY {index} WHERE "
            + " AND ".join(clauses)
            + " ORDER BY json_extract(data,'$.start'),id",
            parameters,
        )
        return [json.loads(row[0]) for row in rows]

    def resolve_gap(self, gap_id: str, intervals: list[dict]):
        from decimal import Decimal, localcontext

        with self.transaction():
            gap = self._get("observations", gap_id)
            if (
                not gap
                or not gap.get("gap")
                or self._get("observation_resolutions", gap_id)
            ):
                raise ValueError("Unresolved source gap required")
            cursor = gap["start"]
            for item in intervals:
                if (
                    item["point_id"] != gap["point_id"]
                    or item["start"] != cursor
                    or item["end"] <= cursor
                    or item.get("gap")
                ):
                    raise ValueError(
                        "Replacement history must continuously cover the gap"
                    )
                cursor = item["end"]
            with localcontext() as ctx:
                ctx.prec = 36
                energy = sum((Decimal(i["energy_kwh"]) for i in intervals), Decimal(0))
            if cursor != gap["end"] or energy != Decimal(gap["energy_kwh"]):
                raise ValueError(
                    "Replacement history must conserve source gap energy and bounds"
                )
            if len(intervals) == 1 and intervals[0]["id"] == gap_id:
                # Identical endpoints are not finer evidence, including price-only changes.
                return False
            self._put(
                "observation_resolutions",
                gap_id,
                {"interval_ids": [i["id"] for i in intervals]},
            )
            for item in intervals:
                self.put_interval(item)
            self._bump()

    def get_record(self, id: str):
        return self._get("records", id)

    def list_records(
        self,
        point_id=None,
        identity_id=None,
        include_void=False,
        *,
        point_ids=None,
        start=None,
        end=None,
        status=None,
    ):
        where, parameters = self._record_filter(
            point_id, identity_id, include_void, point_ids, start, end, status
        )
        return [
            json.loads(row[0])
            for row in self._db.execute(
                f"SELECT data FROM records WHERE {where} ORDER BY start,id", parameters
            )
        ]

    def _record_filter(
        self,
        point_id,
        identity_id,
        include_void,
        point_ids=None,
        start=None,
        end=None,
        status=None,
    ):
        clauses, parameters = [], []
        for field, value in (("point_id", point_id), ("identity_id", identity_id)):
            if value is not None:
                clauses.append(f"{field}=?")
                parameters.append(value)
        if not include_void:
            clauses.append("status!='void'")
        if status is not None:
            clauses.append("status=?")
            parameters.append(status)
        if point_ids is not None:
            clauses.append("point_id IN (" + ",".join("?" for _ in point_ids) + ")")
            parameters.extend(point_ids)
        if start is not None:
            clauses.append("(end IS NULL OR end>?)")
            parameters.append(start)
        if end is not None:
            clauses.append("start<?")
            parameters.append(end)
        return " AND ".join(clauses) or "1", parameters

    def record_page(
        self,
        point_ids,
        *,
        point_id=None,
        identity_id=None,
        include_void=False,
        start=None,
        end=None,
        offset=0,
        limit=50,
    ):
        where, parameters = self._record_filter(
            point_id, identity_id, include_void, point_ids, start, end
        )
        total = self._db.execute(
            f"SELECT COUNT(*) FROM records WHERE {where}", parameters
        ).fetchone()[0]
        records = [
            json.loads(row[0])
            for row in self._db.execute(
                f"SELECT data FROM records WHERE {where} ORDER BY start DESC,id DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            )
        ]
        return records, total

    def overlaps(self, point_id, start, end, exclude_id=""):
        rows = self._db.execute(
            "SELECT id FROM records WHERE point_id=? AND status!='void' AND id!=? AND start<COALESCE(?, '9999-12-31T23:59:59+00:00') AND (end IS NULL OR end>?) ORDER BY start,id",
            (point_id, exclude_id, end, start),
        )
        return [r[0] for r in rows]

    def save_record(
        self, record: dict, segments: list[dict], *, audit: bool = True
    ) -> None:
        with self.transaction():
            if record["status"] != "void" and self.overlaps(
                record["point_id"], record["start"], record["end"], record["id"]
            ):
                raise ValueError("Record interval overlaps an existing record")
            self._db.execute(
                "INSERT INTO records VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET point_id=excluded.point_id,identity_id=excluded.identity_id,start=excluded.start,end=excluded.end,status=excluded.status,data=excluded.data",
                (
                    record["id"],
                    record["point_id"],
                    record["identity_id"],
                    record["start"],
                    record["end"],
                    record["status"],
                    encode(record),
                ),
            )
            self._db.execute("DELETE FROM segments WHERE record_id=?", (record["id"],))
            for index, segment in enumerate(segments):
                self._db.execute(
                    "INSERT INTO segments VALUES (?,?,?,?)",
                    (
                        record["id"],
                        index,
                        segment.get("observation_id"),
                        encode(segment),
                    ),
                )
            if audit:
                self.save_revision(record["id"])
            self._bump()

    def append_record_segments(
        self, record: dict, segments: list[dict], expected_count: int
    ) -> None:
        """Append to the contiguous position sequence without copying old evidence."""
        with self.transaction():
            previous = self.get_record(record["id"])
            if previous is None:
                raise ValueError("Unknown record")
            last = self._db.execute(
                "SELECT position FROM segments WHERE record_id=? ORDER BY position DESC LIMIT 1",
                (record["id"],),
            ).fetchone()
            if (last[0] + 1 if last else 0) != expected_count:
                raise ValueError("Record segment count conflict")
            if previous["revision"] + 1 != record["revision"]:
                raise ValueError("Record revision conflict")
            for index, segment in enumerate(segments, expected_count):
                self._db.execute(
                    "INSERT INTO segments VALUES (?,?,?,?)",
                    (
                        record["id"],
                        index,
                        segment.get("observation_id"),
                        encode(segment),
                    ),
                )
            self._db.execute(
                "UPDATE records SET data=? WHERE id=?", (encode(record), record["id"])
            )
            self._bump()

    def save_revision(self, record_id: str) -> None:
        """Snapshot the current version within the caller's transaction."""
        if not self._db.in_transaction:
            raise ValueError("Saving a revision requires a transaction")
        record = self.get_record(record_id)
        if record is None:
            raise ValueError("Unknown record")
        self._db.execute(
            "INSERT INTO revisions VALUES (?,?,?)",
            (
                record_id,
                record["revision"],
                encode({"record": record, "segments": self.list_segments(record_id)}),
            ),
        )

    def has_known_cost(self, record_id: str) -> bool:
        """Check legacy cost evidence without loading every serialized segment."""
        return bool(
            self._db.execute(
                "SELECT EXISTS(SELECT 1 FROM segments WHERE record_id=? "
                "AND json_extract(data,'$.cost') IS NOT NULL)",
                (record_id,),
            ).fetchone()[0]
        )

    def list_segments(self, record_id: str):
        return [
            json.loads(r[0])
            for r in self._db.execute(
                "SELECT data FROM segments WHERE record_id=? ORDER BY position",
                (record_id,),
            )
        ]

    def list_revisions(self, record_id: str):
        return [
            json.loads(r[0])
            for r in self._db.execute(
                "SELECT data FROM revisions WHERE record_id=? ORDER BY revision",
                (record_id,),
            )
        ]

    def list_revision_records(self, record_id: str):
        """Decode audit records without transferring historical segment payloads."""
        result = []
        for row in self._db.execute(
            "SELECT json_extract(data,'$.record'), "
            "CASE WHEN json_type(data,'$.record.has_known_cost') IS NULL THEN "
            "EXISTS(SELECT 1 FROM json_each(revisions.data,'$.segments') "
            "WHERE json_extract(value,'$.cost') IS NOT NULL) END "
            "FROM revisions WHERE record_id=? ORDER BY revision",
            (record_id,),
        ):
            record = json.loads(row[0])
            if "has_known_cost" not in record:
                record["has_known_cost"] = bool(row[1])
            result.append(record)
        return result

    def get_request(self, request_id: str):
        return self._get("requests", request_id)

    def put_request(self, request_id: str, data: dict):
        with self.transaction():
            if self.get_request(request_id) is not None:
                raise ValueError("Request already exists")
            self._put("requests", request_id, data)

    def put_preview(self, token: str, data: dict):
        with self.transaction():
            self._put("previews", token, data)

    def get_preview(self, token: str):
        return self._get("previews", token)

    def prune_previews(self, now=None, limit=500):
        """Discard bounded abandoned drafts; receipts and consumed bindings are durable."""
        if limit < 1:
            raise ValueError("Prune limit must be positive")
        cutoff = (
            (now or datetime.now(UTC)) - timedelta(seconds=PREVIEW_LIFETIME_SECONDS)
        ).isoformat()
        with self.transaction():
            candidates = self._db.execute(
                "SELECT id,json_extract(data,'$.created_at') IS NULL FROM previews "
                "WHERE json_extract(data,'$.consumed') IS NOT 1 "
                "AND COALESCE(json_extract(data,'$.created_at'),'')<=? "
                "ORDER BY COALESCE(json_extract(data,'$.created_at'),''),id LIMIT ?",
                (cutoff, limit),
            ).fetchall()
            removed = 0
            for token, legacy in candidates:
                if legacy:
                    receipt = self._db.execute(
                        "SELECT json_extract(data,'$.result.id'),json_extract(data,'$.result.point_id'),"
                        "json_extract(data,'$.result.identity_id') FROM requests "
                        "WHERE json_extract(data,'$.digest')=? LIMIT 1",
                        (
                            sha256(
                                encode(["commit_preview", token]).encode()
                            ).hexdigest(),
                        ),
                    ).fetchone()
                    if receipt:
                        self._put(
                            "previews",
                            token,
                            {
                                "consumed": True,
                                "record_id": receipt[0],
                                "point_id": receipt[1],
                                "identity_id": receipt[2],
                            },
                        )
                        continue
                self._db.execute("DELETE FROM previews WHERE id=?", (token,))
                self._db.execute(
                    "DELETE FROM checkpoints WHERE id=?", ("api_preview:" + token,)
                )
                removed += 1
        return removed

    def prune_pending(self):
        """Report candidate progress independently of the public deletion count."""
        return self.get_checkpoint("_prune_progress") is not None

    def prune(self, before: datetime | None = None, limit: int = 500):
        from .core.tariffs import utc

        if limit < 1:
            raise ValueError("Prune limit must be positive")
        removed, remaining = 0, limit
        with self.transaction():
            progress = self.get_checkpoint("_prune_progress") or {
                "cutoff": utc(
                    before or datetime.now(UTC) - timedelta(days=90)
                ).isoformat(),
                "phase": "observations",
                "after": None,
            }
            cutoff = progress["cutoff"]
            for phase in ("observations", "price_versions"):
                if progress["phase"] != phase:
                    continue
                after = progress["after"]
                field = "end" if phase == "observations" else "at"
                # Seek the time index before applying the tied-ID cursor.
                cursor = (
                    f" AND json_extract(data,'$.{field}')>=? AND (json_extract(data,'$.{field}'),id)>(?,?)"
                    if after
                    else ""
                )
                rows = self._db.execute(
                    f"SELECT data FROM {phase} WHERE json_extract(data,'$.{field}')<?"
                    + cursor
                    + f" ORDER BY json_extract(data,'$.{field}'),id LIMIT ?",
                    [cutoff, *([after[0], *after] if after else []), remaining + 1],
                ).fetchall()
                for row in rows[:remaining]:
                    item = json.loads(row[0])
                    progress["after"] = [item[field], item["id"]]
                    if phase == "observations":
                        if (
                            item.get("gap")
                            or self._db.execute(
                                "SELECT 1 FROM segments WHERE observation_id=? LIMIT 1",
                                (item["id"],),
                            ).fetchone()
                            or self.overlaps(
                                item["point_id"], item["start"], item["end"]
                            )
                            or self._db.execute(
                                "SELECT 1 FROM revisions,json_each(revisions.data,'$.segments') AS segment "
                                "WHERE json_extract(segment.value,'$.observation_id')=? LIMIT 1",
                                (item["id"],),
                            ).fetchone()
                        ):
                            continue
                    else:
                        anchor = self._db.execute(
                            "SELECT id FROM price_versions WHERE json_extract(data,'$.point_id')=? "
                            "AND json_extract(data,'$.at')<? ORDER BY json_extract(data,'$.at') DESC,id DESC LIMIT 1",
                            (item["point_id"], cutoff),
                        ).fetchone()
                        if anchor[0] == item["id"]:
                            continue
                        following = self._db.execute(
                            "SELECT json_extract(data,'$.at') FROM price_versions WHERE json_extract(data,'$.point_id')=? "
                            "AND json_extract(data,'$.at')>=? AND (json_extract(data,'$.at'),id)>(?,?) ORDER BY json_extract(data,'$.at'),id LIMIT 1",
                            (item["point_id"], item["at"], item["at"], item["id"]),
                        ).fetchone()
                        right = following[0] if following else None
                        if (
                            self._db.execute(
                                "SELECT 1 FROM observations WHERE json_extract(data,'$.point_id')=? "
                                "AND json_extract(data,'$.start')<COALESCE(?,'9999') AND json_extract(data,'$.end')>? LIMIT 1",
                                (item["point_id"], right, item["at"]),
                            ).fetchone()
                            or self._db.execute(
                                "SELECT 1 FROM records WHERE point_id=? AND status='active' "
                                "AND start<COALESCE(?,'9999') LIMIT 1",
                                (item["point_id"], right),
                            ).fetchone()
                            or self._db.execute(
                                "SELECT 1 FROM revisions WHERE json_extract(data,'$.record.point_id')=? "
                                "AND json_extract(data,'$.record.end') IS NOT NULL "
                                "AND json_extract(data,'$.record.start')<COALESCE(?,'9999') "
                                "AND json_extract(data,'$.record.end')>? LIMIT 1",
                                (item["point_id"], right, item["at"]),
                            ).fetchone()
                        ):
                            continue
                        key = "_price_gaps:" + item["point_id"]
                        spans = sorted(
                            [
                                *(self.get_checkpoint(key) or []),
                                {"start": item["at"], "end": right},
                            ],
                            key=lambda span: span["start"],
                        )
                        merged = []
                        for span in spans:
                            if merged and merged[-1]["end"] == span["start"]:
                                merged[-1]["end"] = span["end"]
                            else:
                                merged.append(span)
                        self._put("checkpoints", key, merged)
                    self._db.execute(f"DELETE FROM {phase} WHERE id=?", (item["id"],))
                    removed += 1
                if len(rows) > remaining:
                    self._put("checkpoints", "_prune_progress", progress)
                    break
                remaining -= len(rows)
                progress.update(phase="price_versions", after=None)
            else:
                self._db.execute("DELETE FROM checkpoints WHERE id='_prune_progress'")
            if removed:
                self._bump()
        return removed
