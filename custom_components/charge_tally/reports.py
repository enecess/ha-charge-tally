"""Independent report snapshots projected from authorized summary contributions."""

from copy import deepcopy
from datetime import datetime

MAX_REPORT_RECORDS = 5000
MAX_REPORT_SEGMENTS = 250000


def build_report(
    ledger,
    summary: dict,
    *,
    scope: dict,
    currency: str,
    timezone: str,
    generated_at: datetime,
) -> dict:
    """Resolve only selected names inside the caller's worker transaction."""
    snapshot = deepcopy(summary)
    rows = snapshot.pop("records")
    scope = deepcopy(scope)
    point_names, identity_names = {}, {}

    def name(cache, getter, object_id):
        if object_id is None:
            return None
        if object_id not in cache:
            cache[object_id] = (getter(object_id) or {}).get("name")
        return cache[object_id]

    for row in rows:
        record = row["record"]
        row["point_name"] = name(point_names, ledger.get_point, record["point_id"])
        row["identity_name"] = name(
            identity_names, ledger.get_identity, record["identity_id"]
        )
    scope["point_name"] = name(point_names, ledger.get_point, scope.get("point_id"))
    scope["identity_name"] = name(
        identity_names, ledger.get_identity, scope.get("identity_id")
    )
    return {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "data_version": ledger.data_version(),
        "currency": currency,
        "timezone": timezone,
        "scope": scope,
        "summary": snapshot,
        "rows": rows,
    }
