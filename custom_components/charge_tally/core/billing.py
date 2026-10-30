"""Pure public billing projections from detailed accounting evidence."""

from bisect import bisect_left, bisect_right
from datetime import datetime
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from .tariffs import calendar_boundaries, elapsed, utc


def display_parts(parts: list[dict], timezone: ZoneInfo) -> list[dict]:
    """Localize raw evidence copies, allocating each sample at display midnight."""
    if not parts:
        return []
    instants = [
        (
            utc(datetime.fromisoformat(part["start"])),
            utc(datetime.fromisoformat(part["end"])),
        )
        for part in parts
    ]
    boundaries = calendar_boundaries(
        min(start for start, _ in instants),
        max(end for _, end in instants),
        timezone.key,
        {0},
    )
    result = []
    with localcontext() as context:
        context.prec = 36
        for part, (start, end) in zip(parts, instants):
            cuts = [
                start,
                *boundaries[
                    bisect_right(boundaries, start) : bisect_left(boundaries, end)
                ],
                end,
            ]
            energy = Decimal(part["energy_kwh"])
            cost = None if part["cost"] is None else Decimal(part["cost"])
            allocated_energy = allocated_cost = Decimal(0)
            for left, right in zip(cuts, cuts[1:]):
                cumulative_energy = (
                    energy
                    if right == end
                    else energy * elapsed(start, right) / elapsed(start, end)
                )
                cumulative_cost = (
                    None
                    if cost is None
                    else cost
                    if right == end
                    else cost * elapsed(start, right) / elapsed(start, end)
                )
                result.append(
                    {
                        **part,
                        "start": left.isoformat(),
                        "end": right.isoformat(),
                        "local_date": left.astimezone(timezone).date().isoformat(),
                        "energy_kwh": str(cumulative_energy - allocated_energy),
                        "cost": None
                        if cumulative_cost is None
                        else str(cumulative_cost - allocated_cost),
                        "quality": list(part["quality"]),
                    }
                )
                allocated_energy = cumulative_energy
                if cumulative_cost is not None:
                    allocated_cost = cumulative_cost
    return result


def reconcile_display_totals(parts: list[dict], *projections: list[dict]) -> None:
    """Conserve raw totals after display merging changes Decimal addition order."""
    with localcontext() as context:
        context.prec = 36
        for field in ("energy_kwh", "cost"):
            total = sum(
                (Decimal(part[field]) for part in parts if part[field] is not None),
                Decimal(0),
            )
            for rows in projections:
                values = [
                    Decimal(row[field]) if row[field] is not None else Decimal(0)
                    for row in rows
                ]
                last = next(
                    (
                        index
                        for index in range(len(values) - 1, -1, -1)
                        if values[index]
                    ),
                    None,
                )
                if last is None:
                    continue
                prefix = sum(values[:last], Decimal(0))
                with localcontext() as exact:
                    exact.prec = (
                        max(total.adjusted(), prefix.adjusted())
                        - min(
                            value.as_tuple().exponent
                            for value in (total, prefix, *values)
                        )
                        + 2
                    )
                    # A tiny final value cannot absorb an opposite-sign remainder.
                    # Adjust earlier nonzero values without reversing row signs.
                    if (values[last] > 0 and prefix > total) or (
                        values[last] < 0 and prefix < total
                    ):
                        for index in range(last - 1, -1, -1):
                            if not values[index]:
                                continue
                            values[index] = (
                                max(Decimal(0), values[index] + total - prefix)
                                if values[index] > 0
                                else min(Decimal(0), values[index] + total - prefix)
                            )
                            rows[index][field] = str(values[index])
                            with localcontext() as rounded:
                                rounded.prec = 36
                                prefix = sum(values[:last], Decimal(0))
                            if (values[last] > 0 and prefix <= total) or (
                                values[last] < 0 and prefix >= total
                            ):
                                break
                    rows[last][field] = str(total - prefix)


def billing_segments(parts: list[dict]) -> list[dict]:
    """Merge consecutive equivalent parts without altering stored evidence."""
    result = []
    previous_key = previous_end = None
    with localcontext() as context:
        context.prec = 36
        for part in parts:
            start, end = (
                utc(datetime.fromisoformat(part["start"])),
                utc(datetime.fromisoformat(part["end"])),
            )
            price = None if part["unit_price"] is None else Decimal(part["unit_price"])
            energy = Decimal(part["energy_kwh"])
            cost = None if part["cost"] is None else Decimal(part["cost"])
            key = (
                part["local_date"],
                price,
                part["cost_basis"],
                frozenset(part["quality"]),
                cost is None,
            )
            if result and previous_end == start and previous_key == key:
                group = result[-1]
                group["end"] = part["end"]
                group["energy_kwh"] = str(Decimal(group["energy_kwh"]) + energy)
                if cost is not None:
                    group["cost"] = str(Decimal(group["cost"]) + cost)
            else:
                result.append(
                    {
                        "start": part["start"],
                        "end": part["end"],
                        "local_date": part["local_date"],
                        "unit_price": part["unit_price"],
                        "cost_basis": part["cost_basis"],
                        "quality": list(part["quality"]),
                        "energy_kwh": str(energy),
                        "cost": None if cost is None else str(cost),
                    }
                )
            previous_key, previous_end = key, end
    return result


def billing_periods(parts: list[dict], quality_spans=()) -> list[dict]:
    """Project continuous tariff periods independently of sampling quality."""
    missing = [
        (
            utc(datetime.fromisoformat(span["start"])),
            utc(datetime.fromisoformat(span["end"])),
        )
        for span in quality_spans
        if "missing_energy" in span["quality"]
    ]
    result = []
    previous_key = previous_end = period_start = None
    with localcontext() as context:
        context.prec = 36
        for part in parts:
            start, end = (
                utc(datetime.fromisoformat(part["start"])),
                utc(datetime.fromisoformat(part["end"])),
            )
            price = None if part["unit_price"] is None else Decimal(part["unit_price"])
            energy = Decimal(part["energy_kwh"])
            cost = None if part["cost"] is None else Decimal(part["cost"])
            key = (part["local_date"], price, part["cost_basis"], cost is None)
            if (
                result
                and previous_end == start
                and previous_key == key
                and not any(
                    left < end and right > period_start for left, right in missing
                )
            ):
                group = result[-1]
                group["end"] = part["end"]
                group["energy_kwh"] = str(Decimal(group["energy_kwh"]) + energy)
                group["quality"] = sorted(set(group["quality"]) | set(part["quality"]))
                if cost is not None:
                    group["cost"] = str(Decimal(group["cost"]) + cost)
            else:
                result.append(
                    {
                        "start": part["start"],
                        "end": part["end"],
                        "local_date": part["local_date"],
                        "unit_price": part["unit_price"],
                        "cost_basis": part["cost_basis"],
                        "quality": sorted(set(part["quality"])),
                        "energy_kwh": str(energy),
                        "cost": None if cost is None else str(cost),
                    }
                )
                period_start = start
            previous_key, previous_end = key, end
    return result
