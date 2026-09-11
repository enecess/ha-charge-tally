"""Fixtures exercise the real Home Assistant runtime."""
import pytest
import custom_components.charge_tally  # Load the worktree before HA adjusts package paths.


@pytest.fixture(autouse=True)
def custom_components_enabled(enable_custom_integrations):
    """Permit loading this worktree's custom integration."""
