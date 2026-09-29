"""Pure configuration normalization shared by HA flows and runtime callers."""

import re
from copy import deepcopy
from math import isfinite

from .const import DEFAULT_MAX_GAP_SECONDS, INPUT_MODES, PERIODS
from .core.tariffs import DailySchedule
from .core.units import decimal_value


def validate_name(value):
    """Normalize a visible name without using it as an identity."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid_name")
    return value.strip()


BUILTIN_IDENTITY_NAME = "Unassigned"


def identity_name_key(value):
    return validate_name(value).casefold()


def validate_identity_name(value):
    name = validate_name(value)
    if identity_name_key(name) == identity_name_key(BUILTIN_IDENTITY_NAME):
        raise ValueError("duplicate_name")
    return name


def validate_detection(data):
    """Validate hysteresis and positive durations in watts and seconds."""
    if not isinstance(data, dict) or not isinstance(data.get("enabled", False), bool):
        raise ValueError("invalid_detection")
    if not data.get("enabled", False):
        return {"enabled": False}
    try:
        start = decimal_value(data["start_w"], nonnegative=True)
        end = decimal_value(data["end_w"], nonnegative=True)
        start_seconds = decimal_value(data.get("start_seconds", 30))
        end_seconds = decimal_value(data.get("end_seconds", 300))
        if end >= start or any(
            not isfinite(float(value)) or float(value) <= 0
            for value in (start_seconds, end_seconds)
        ):
            raise ValueError
    except (KeyError, ValueError) as err:
        raise ValueError("invalid_detection") from err
    return {
        "enabled": True,
        "start_w": str(start),
        "end_w": str(end),
        "start_seconds": float(start_seconds),
        "end_seconds": float(end_seconds),
    }


def validate_price(data):
    """Keep exact decimal prices and validate a complete local-clock schedule."""
    if not isinstance(data, dict):
        raise ValueError("invalid_price")
    mode = data.get("mode")
    try:
        if mode == "static":
            return {"mode": mode, "value": str(decimal_value(data["value"]))}
        if mode == "dynamic":
            entity_id = _entity(data.get("entity_id"))
            unit = data.get("unit")
            if not isinstance(unit, str) or not re.fullmatch(
                r"[A-Z]{3}/(?:Wh|kWh|MWh)", unit
            ):
                raise ValueError("invalid_price_unit")
            return {"mode": mode, "entity_id": entity_id, "unit": unit}
        if mode == "tou":
            try:
                DailySchedule(data["schedule"])
                rows = [
                    {
                        "start": row["start"],
                        "end": row["end"],
                        "price": str(decimal_value(row["price"])),
                    }
                    for row in data["schedule"]
                ]
            except (KeyError, ValueError, TypeError) as err:
                raise ValueError("invalid_schedule") from err
            return {"mode": mode, "schedule": rows}
    except (KeyError, TypeError) as err:
        raise ValueError("invalid_price") from err
    except ValueError as err:
        if str(err) in ("invalid_price_unit", "invalid_schedule"):
            raise
        raise ValueError("invalid_price") from err
    raise ValueError("invalid_price")


def _entity(value):
    if not isinstance(value, str) or not re.fullmatch(r"sensor\.[a-z0-9_]+", value):
        raise ValueError("invalid_source")
    return value


def validate_point(data: dict, existing: list[dict]) -> dict:
    """Normalize a point; existing excludes the point currently being edited."""
    result = {
        "name": validate_name(data.get("name")),
        "input_mode": data.get("input_mode"),
    }
    mode = result["input_mode"]
    if mode not in INPUT_MODES:
        raise ValueError("invalid_input_mode")
    for field, required in (
        ("energy_entity", mode != "power"),
        ("power_entity", mode != "energy"),
    ):
        if required:
            result[field] = _entity(data.get(field))
    selected = {
        result[key] for key in ("energy_entity", "power_entity") if key in result
    }
    if len(selected) != (2 if mode == "energy_power" else 1):
        raise ValueError("duplicate_source")
    for other in existing:
        if selected.intersection(
            other.get(key) for key in ("energy_entity", "power_entity")
        ):
            raise ValueError("duplicate_source")
    detection = validate_detection(deepcopy(data.get("detection", {"enabled": False})))
    if mode == "energy" and detection["enabled"]:
        raise ValueError("invalid_detection")
    result["detection"] = detection
    resetting = data.get("resetting", True)
    if not isinstance(resetting, bool):
        raise ValueError("invalid_source")
    result["resetting"] = resetting
    try:
        gap = decimal_value(data.get("max_gap_seconds", DEFAULT_MAX_GAP_SECONDS))
        if not isfinite(float(gap)) or float(gap) <= 0:
            raise ValueError
        result["max_gap_seconds"] = float(gap)
    except ValueError as err:
        raise ValueError("invalid_gap") from err
    periods = data.get("periods", list(PERIODS))
    if (
        not isinstance(periods, list)
        or any(item not in PERIODS for item in periods)
        or len(set(periods)) != len(periods)
    ):
        raise ValueError("invalid_periods")
    result["periods"] = list(periods)
    result["price"] = validate_price(data.get("price"))
    return result
