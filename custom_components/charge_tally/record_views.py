"""Shared public record projections, separate from persisted evidence."""

from .core.billing import billing_periods, billing_segments


def record_view(record: dict, parts: list[dict] | None = None) -> dict:
    """Hide internal incremental accounting cursors."""
    result = {
        key: value
        for key, value in record.items()
        if key not in {"_accounted_until", "_segment_count"}
    }
    if parts is not None:
        result["has_known_cost"] = any(part["cost"] is not None for part in parts)
    return result


def revision_view(revision: dict) -> dict:
    """Project revision evidence without modifying the ledger snapshot."""
    return {
        **revision,
        "record": record_view(revision["record"], revision["segments"]),
        "segments": billing_segments(revision["segments"]),
    }


def detail_view(
    record: dict, parts: list[dict], revisions: list[dict], *, include_history=True
) -> dict:
    """Build the shared public record detail."""
    return {
        "record": record_view(record, parts),
        "segments": billing_segments(parts),
        "billing_periods": billing_periods(parts, record.get("quality_spans", ())),
        "revisions": [revision_view(revision) for revision in revisions]
        if include_history
        else [],
    }
