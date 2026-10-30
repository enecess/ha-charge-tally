"""Pure public billing projections from detailed accounting evidence."""

from datetime import datetime
from decimal import Decimal, localcontext

from .tariffs import utc


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
