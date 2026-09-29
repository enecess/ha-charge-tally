"""Shared public record projections, separate from persisted evidence."""

from .core.billing import billing_segments


def record_view(record: dict) -> dict:
    """Hide internal incremental accounting cursors."""
    return {
        key: value
        for key, value in record.items()
        if key not in {"_accounted_until", "_segment_count"}
    }


def revision_view(revision: dict) -> dict:
    """Project revision evidence without modifying the ledger snapshot."""
    return {
        **revision,
        "record": record_view(revision["record"]),
        "segments": billing_segments(revision["segments"]),
    }


def detail_view(record: dict, parts: list[dict], revisions: list[dict]) -> dict:
    """Build the shared public record detail."""
    return {
        "record": record_view(record),
        "segments": billing_segments(parts),
        "revisions": [revision_view(revision) for revision in revisions],
    }
