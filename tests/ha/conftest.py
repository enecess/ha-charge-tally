"""Fixtures exercise the real Home Assistant runtime."""

import pytest

import custom_components.charge_tally  # noqa: F401  # Load this checkout before HA changes paths.


@pytest.fixture(autouse=True)
def custom_components_enabled(enable_custom_integrations):
    """Permit loading this worktree's custom integration."""


@pytest.fixture
def hass_storage():
    """Use real Store I/O so ownership durability is exercised."""
    return {}


@pytest.fixture
def hass_config_dir(tmp_path):
    """Keep each runtime's real storage isolated from other tests."""
    return str(tmp_path)


@pytest.fixture(autouse=True)
def isolated_hass_config(hass, tmp_path):
    """Isolate real Store I/O on plugins predating hass_config_dir."""
    hass.config.config_dir = str(tmp_path)
