"""Validated decimal unit conversion."""
from decimal import Decimal, InvalidOperation, localcontext


def decimal_value(value: object, *, nonnegative: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError('Boolean is not a measurement')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as err:
        raise ValueError('Invalid decimal value') from err
    if not result.is_finite() or (nonnegative and result < 0):
        raise ValueError('Measurement must be finite and in range')
    return result


def _convert(value: object, unit: str, factors: dict[str, str]) -> Decimal:
    if unit not in factors:
        raise ValueError('Unsupported unit')
    with localcontext() as ctx:
        ctx.prec = 36
        return decimal_value(value, nonnegative=True) * Decimal(factors[unit])


def energy_kwh(value: object, unit: str) -> Decimal:
    return _convert(value, unit, {'Wh': '.001', 'kWh': '1', 'MWh': '1000'})


def power_w(value: object, unit: str) -> Decimal:
    return _convert(value, unit, {'W': '1', 'kW': '1000', 'MW': '1000000'})


def price_per_kwh(value: object, unit: str, currency: str) -> Decimal:
    factors = {f'{currency}/Wh': '1000', f'{currency}/kWh': '1', f'{currency}/MWh': '.001'}
    if not currency or unit not in factors:
        raise ValueError('Unsupported price unit or currency mismatch')
    with localcontext() as ctx:
        ctx.prec = 36
        return decimal_value(value) * Decimal(factors[unit])
