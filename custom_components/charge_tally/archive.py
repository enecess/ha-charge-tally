"""Transactional archive summaries, deletion and identity audit preservation."""

import json
from decimal import Decimal, localcontext
from hashlib import sha256

from .ledger import encode


def archive_ids(value):
    """Normalize single and batch selections before touching storage."""
    values = [value] if isinstance(value, str) else value
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(item, str) or not item for item in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("archive_not_found")
    return sorted(values)


class ArchiveManager:
    def __init__(self, ledger):
        self.ledger = ledger

    def catalog(self, configured_points, configured_identities):
        def brief(item):
            return {"id": item["id"], "name": item.get("name", item["id"])}

        identities = self.ledger.list_identities()
        return {
            "points": [
                brief(p)
                for p in self.ledger.list_points()
                if p.get("active", True) is False and p["id"] not in configured_points
            ],
            "identities": [
                brief(i)
                for i in identities
                if i.get("active", True) is False
                and i["id"] not in configured_identities
                and i["id"] != "unassigned"
            ],
            "targets": [
                brief(i)
                for i in identities
                if i["id"] == "unassigned"
                or (i.get("active", True) and i["id"] in configured_identities)
            ],
        }

    def _object(self, kind, object_id, configured_points, configured_identities):
        if kind not in ("point", "identity"):
            raise ValueError("archive_not_found")
        item = (self.ledger.get_point if kind == "point" else self.ledger.get_identity)(
            object_id
        )
        if item is None:
            raise ValueError("archive_not_found")
        configured = configured_points if kind == "point" else configured_identities
        if (
            object_id in configured
            or item.get("active", True) is not False
            or (kind == "identity" and object_id == "unassigned")
        ):
            raise ValueError("archive_configured")
        return item

    def _rows(self, table):
        return [
            (id_, json.loads(data))
            for id_, data in self.ledger._db.execute(
                f"SELECT id,data FROM {table} ORDER BY id"
            )
        ]

    def _related(self, kind, object_id, records):
        record_ids = {r["id"] for r in records}
        revisions = [
            (id_, revision, json.loads(data))
            for id_, revision, data in self.ledger._db.execute(
                "SELECT record_id,revision,data FROM revisions ORDER BY record_id,revision"
            )
            if id_ in record_ids
            or json.loads(data)["record"].get(kind + "_id") == object_id
        ]
        # Include migrated records: their cached audit data is stale too.
        related_ids = record_ids | {row[0] for row in revisions}
        segments = [(r["id"], self.ledger.list_segments(r["id"])) for r in records]
        observations = [
            (id_, data)
            for id_, data in self._rows("observations")
            if kind == "point" and data.get("point_id") == object_id
        ]
        observation_ids = {id_ for id_, _ in observations}
        prices = [
            (id_, data)
            for id_, data in self._rows("price_versions")
            if kind == "point" and data.get("point_id") == object_id
        ]
        resolutions = [
            (id_, data)
            for id_, data in self._rows("observation_resolutions")
            if id_ in observation_ids
        ]
        tokens, request_ids = set(), set()

        def refers(value):
            if isinstance(value, dict):
                if (
                    value.get(kind + "_id") == object_id
                    or value.get("record_id") in related_ids
                    or value.get("id") in related_ids
                    or value.get("token") in tokens
                    or value.get("request_id") in request_ids
                ):
                    return True
                return any(refers(v) for v in value.values())
            if isinstance(value, list):
                return any(refers(v) for v in value)
            return False

        previews = [(id_, data) for id_, data in self._rows("previews") if refers(data)]
        tokens.update(id_ for id_, _ in previews)
        requests = [(id_, data) for id_, data in self._rows("requests") if refers(data)]
        request_ids.update(id_ for id_, _ in requests)
        candidates = [
            (id_, data)
            for id_, data in self._rows("checkpoints")
            if id_.startswith(
                (
                    "api_preview:",
                    "api_request:",
                    "runtime_request:",
                    "command_time:",
                    "_price_gaps:",
                )
            )
        ]
        checkpoints = {}
        # Follow request/preview bindings before removing their command-time entries.
        changed = True
        while changed:
            changed = False
            for id_, data in candidates:
                if id_ in checkpoints:
                    continue
                prefix, suffix = id_.split(":", 1)
                matched = refers(data)
                matched |= prefix == "api_preview" and suffix in tokens
                matched |= prefix == "command_time" and suffix in request_ids
                matched |= (
                    prefix == "_price_gaps" and kind == "point" and suffix == object_id
                )
                matched |= prefix == "runtime_request" and suffix in request_ids
                matched |= prefix == "api_request" and "api:" + suffix in request_ids
                if not matched:
                    continue
                checkpoints[id_] = data
                if prefix == "api_preview":
                    tokens.add(suffix)
                elif prefix == "runtime_request":
                    request_ids.add(suffix)
                elif prefix == "api_request":
                    request_ids.add("api:" + suffix)
                if isinstance(data, dict) and isinstance(data.get("payload"), dict):
                    request_id = data["payload"].get("request_id")
                    if request_id:
                        request_ids.add(request_id)
                changed = True
        return dict(
            revisions=revisions,
            segments=segments,
            observations=observations,
            prices=prices,
            resolutions=resolutions,
            previews=previews,
            requests=requests,
            checkpoints=sorted(checkpoints.items()),
        )

    def _snapshot(
        self,
        kind,
        object_id,
        configured_points,
        configured_identities,
        target_identity_id,
    ):
        item = self._object(kind, object_id, configured_points, configured_identities)
        records = self.ledger.list_records(
            include_void=True, **{kind + "_id": object_id}
        )
        active_count = sum(r["status"] == "active" for r in records)
        if kind == "identity" and active_count:
            raise ValueError("archive_busy")
        target = None
        if target_identity_id is not None:
            target = self.ledger.get_identity(target_identity_id)
            if (
                kind != "identity"
                or not target
                or target_identity_id == object_id
                or (
                    target_identity_id != "unassigned"
                    and (
                        target_identity_id not in configured_identities
                        or not target.get("active", True)
                    )
                )
            ):
                raise ValueError("archive_target")
        related = self._related(kind, object_id, records)
        fingerprint = sha256(
            encode([item, records, related, target, self.ledger.currency]).encode()
        ).hexdigest()
        with localcontext() as context:
            context.prec = 36
            energy = str(
                sum((Decimal(r.get("energy_kwh", "0")) for r in records), Decimal(0))
            )
            cost = str(
                sum((Decimal(r.get("known_cost", "0")) for r in records), Decimal(0))
            )
        latest_ended_at = max((r["end"] for r in records if r["end"]), default=None)
        summary = dict(
            kind=kind,
            id=object_id,
            name=item.get("name", object_id),
            record_count=len(records),
            void_count=sum(r["status"] == "void" for r in records),
            revision_count=len(related["revisions"]),
            start=min((r["start"] for r in records), default=None),
            active_count=active_count,
            end=None if active_count else latest_ended_at,
            latest_ended_at=latest_ended_at,
            energy_kwh=energy,
            known_cost=cost,
            cost_complete=all(r.get("cost_complete", False) for r in records),
            currency=self.ledger.currency,
            fingerprint=fingerprint,
            target_identity_id=target_identity_id,
            target_name=target.get("name", target_identity_id) if target else None,
        )
        return summary, records, related

    def _batch_snapshot(
        self,
        kind,
        object_id,
        configured_points,
        configured_identities,
        target_identity_id,
    ):
        ids = archive_ids(object_id)
        snapshots = [
            self._snapshot(
                kind, id_, configured_points, configured_identities, target_identity_id
            )
            for id_ in ids
        ]
        summaries = [item[0] for item in snapshots]
        summary = dict(summaries[0])
        summary.update(ids=ids, object_count=len(ids), items=summaries)
        if isinstance(object_id, str):
            return summary, snapshots
        summary.update(
            id=ids,
            name=", ".join(item["name"] for item in summaries),
            fingerprint=sha256(
                encode(
                    [kind, ids, [item["fingerprint"] for item in summaries]]
                ).encode()
            ).hexdigest(),
            revision_count=len(
                {
                    (record_id, revision)
                    for _, _, related in snapshots
                    for record_id, revision, _ in related["revisions"]
                }
            ),
            start=min((s["start"] for s in summaries if s["start"]), default=None),
            latest_ended_at=max(
                (s["latest_ended_at"] for s in summaries if s["latest_ended_at"]),
                default=None,
            ),
            cost_complete=all(s["cost_complete"] for s in summaries),
        )
        for key in ("record_count", "void_count", "active_count"):
            summary[key] = sum(s[key] for s in summaries)
        summary["end"] = None if summary["active_count"] else summary["latest_ended_at"]
        with localcontext() as context:
            context.prec = 36
            for key in ("energy_kwh", "known_cost"):
                summary[key] = str(
                    sum((Decimal(s[key]) for s in summaries), Decimal(0))
                )
        return summary, snapshots

    def preview(
        self,
        kind,
        object_id,
        configured_points,
        configured_identities,
        target_identity_id=None,
    ):
        with self.ledger.transaction():
            return self._batch_snapshot(
                kind,
                object_id,
                configured_points,
                configured_identities,
                target_identity_id,
            )[0]

    def delete(
        self,
        kind,
        object_id,
        fingerprint,
        configured_points,
        configured_identities,
        target_identity_id=None,
    ):
        with self.ledger.transaction():
            summary, snapshots = self._batch_snapshot(
                kind,
                object_id,
                configured_points,
                configured_identities,
                target_identity_id,
            )
            if (
                kind == "identity"
                and summary["record_count"]
                and target_identity_id is None
            ):
                raise ValueError("archive_target")
            if summary["fingerprint"] != fingerprint:
                raise ValueError("archive_stale")
            # Validate the whole batch before changes can invalidate shared evidence.
            for item, records, related in snapshots:
                self._delete_snapshot(item, records, related)
            return dict(
                kind=kind,
                id=summary["id"],
                ids=summary["ids"],
                object_count=summary["object_count"],
                record_count=summary["record_count"],
                transferred_count=summary["record_count"] if kind == "identity" else 0,
            )

    def _delete_snapshot(self, summary, records, related):
        kind, object_id = summary["kind"], summary["id"]
        db = self.ledger._db
        if kind == "point":
            for record_id, revision, _ in related["revisions"]:
                db.execute(
                    "DELETE FROM revisions WHERE record_id=? AND revision=?",
                    (record_id, revision),
                )
            for record in records:
                db.execute("DELETE FROM segments WHERE record_id=?", (record["id"],))
                db.execute("DELETE FROM records WHERE id=?", (record["id"],))
            for table, key in [
                ("observation_resolutions", "resolutions"),
                ("observations", "observations"),
                ("price_versions", "prices"),
            ]:
                for id_, _ in related[key]:
                    db.execute(f"DELETE FROM {table} WHERE id=?", (id_,))
            db.execute("DELETE FROM points WHERE id=?", (object_id,))
        else:
            for record_id, revision, data in related["revisions"]:
                if data["record"]["identity_id"] == object_id:
                    data["record"]["identity_name"] = summary["name"]
                    db.execute(
                        "UPDATE revisions SET data=? WHERE record_id=? AND revision=?",
                        (encode(data), record_id, revision),
                    )
            for record in records:
                record.update(
                    identity_id=summary["target_identity_id"],
                    revision=record["revision"] + 1,
                )
                record.pop("identity_name", None)
                self.ledger.save_record(record, self.ledger.list_segments(record["id"]))
            db.execute("DELETE FROM identities WHERE id=?", (object_id,))
        for table in ("previews", "requests", "checkpoints"):
            for id_, _ in related[table]:
                db.execute(f"DELETE FROM {table} WHERE id=?", (id_,))
        self.ledger._bump()
