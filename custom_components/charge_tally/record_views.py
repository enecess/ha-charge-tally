"""Shared public record projections, separate from persisted evidence."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .core.billing import billing_periods, billing_segments, display_parts


class InvalidDisplayTimezone(ValueError):
    """An authorized display request contains an unknown timezone."""


def display_zone(timezone: str) -> ZoneInfo:
    """Validate a display context once before recovery or ledger writes."""
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise InvalidDisplayTimezone("Invalid display timezone") from None


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
    record: dict,
    parts: list[dict],
    revisions: list[dict],
    *,
    include_history=True,
    display_timezone: ZoneInfo | None = None,
) -> dict:
    """Build the shared public record detail."""
    localized = (
        display_parts(parts, display_timezone)
        if display_timezone is not None
        else parts
    )
    result = {
        "record": record_view(record, parts),
        "segments": billing_segments(parts),
        "billing_periods": billing_periods(localized, record.get("quality_spans", ())),
        "revisions": [revision_view(revision) for revision in revisions]
        if include_history
        else [],
    }
    if display_timezone is not None:
        result.update(
            display_timezone=display_timezone.key,
            display_segments=billing_segments(localized),
        )
    return result
