"""Shared native currency selection for setup and existing ledgers."""

from homeassistant.generated.currencies import ACTIVE_CURRENCIES
from homeassistant.helpers import selector


def currency_selector(current: str | None = None) -> selector.SelectSelector:
    """Offer all HA currencies, retaining an existing ledger's retired code."""
    currencies = set(ACTIVE_CURRENCIES)
    if current is not None:
        currencies.add(current)
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=sorted(currencies),
            mode=selector.SelectSelectorMode.DROPDOWN,
            sort=True,
            translation_key="currency",
            multiple=False,
            custom_value=False,
        )
    )
