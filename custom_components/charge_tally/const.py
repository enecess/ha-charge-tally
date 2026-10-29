"""Shared integration identifiers and configuration defaults."""

DOMAIN = "charge_tally"
NAME = "Charge Tally"
VERSION = "0.1.2"
INPUT_MODES = ("energy", "power", "energy_power")
PERIODS = ("daily", "monthly", "yearly")
DEFAULT_MAX_GAP_SECONDS = 600
UNAVAILABLE_TIMEOUT_SECONDS = 300
RESTRICTED_POINT_FIELDS = (
    "input_mode",
    "energy_entity",
    "power_entity",
    "detection",
    "resetting",
    "max_gap_seconds",
)
