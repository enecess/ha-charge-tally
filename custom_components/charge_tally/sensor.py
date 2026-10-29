"""Live cumulative energy and record state entities."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)

from .entity import TallyEntity, setup_entities

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigSubentry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import ChargeTallyConfigEntry
    from .runtime import Runtime


def record_attributes(record: dict[str, Any] | None) -> dict[str, Any]:
    return (
        {
            "record_id": record["id"],
            "record_revision": record["revision"],
            "identity_id": record["identity_id"],
            "start": record["start"],
        }
        if record
        else {}
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ChargeTallyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    def factory(runtime: Runtime, sub: ConfigSubentry) -> list[TallyEntity]:
        if sub.subentry_type == "point":
            return [
                Energy(runtime, sub),
                Status(runtime, sub),
                RecordSensor(runtime, sub, "energy"),
                RecordSensor(runtime, sub, "cost"),
            ]
        return [
            IdentitySensor(runtime, sub.subentry_id, sub.data["name"], period, metric)
            for period in ("daily", "monthly", "yearly", "total")
            for metric in ("energy", "cost")
        ]

    await setup_entities(hass, entry, async_add_entities, factory)
    async_add_entities(
        [
            IdentitySensor(
                entry.runtime_data, "unassigned", "Unassigned", period, metric
            )
            for period in ("daily", "monthly", "yearly", "total")
            for metric in ("energy", "cost")
        ]
    )


class Energy(TallyEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, runtime: Runtime, sub: ConfigSubentry) -> None:
        super().__init__(
            runtime,
            sub.subentry_id,
            "energy",
            sub.data["name"] + " Energy",
            sub.data["name"],
        )

    @property
    def native_value(self) -> str | None:
        return self.point["normalized_energy_kwh"] if self.point else None


class Status(TallyEntity, SensorEntity):
    def __init__(self, runtime: Runtime, sub: ConfigSubentry) -> None:
        super().__init__(
            runtime,
            sub.subentry_id,
            "status",
            sub.data["name"] + " Status",
            sub.data["name"],
        )

    @property
    def native_value(self) -> str | None:
        return self.point["status"] if self.point else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return (
            {
                "quality": self.point["quality"],
                "error": self.point.get("error"),
                **record_attributes(self.point.get("active_record")),
            }
            if self.point
            else {}
        )


class RecordSensor(TallyEntity, SensorEntity):
    def __init__(self, runtime: Runtime, sub: ConfigSubentry, metric: str) -> None:
        super().__init__(
            runtime,
            sub.subentry_id,
            "record_" + metric,
            sub.data["name"] + " Record " + metric,
            sub.data["name"],
        )
        self.metric = metric
        self._attr_suggested_display_precision = 3 if metric == "energy" else 2
        self._attr_native_unit_of_measurement = (
            "kWh" if metric == "energy" else runtime.entry.data["currency"]
        )

    @property
    def record(self) -> dict[str, Any] | None:
        point = self.point
        return (
            (point.get("active_record") or point.get("last_record")) if point else None
        )

    @property
    def native_value(self) -> str | None:
        record = self.record
        return (
            record["energy_kwh" if self.metric == "energy" else "known_cost"]
            if record
            else None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        record = self.record
        return (
            {
                "known_cost": record["known_cost"],
                "has_known_cost": record["has_known_cost"],
                "cost_complete": record["cost_complete"],
                "quality": record["quality"],
                "record_status": record["status"],
                "end": record["end"],
                "end_reason": record.get("end_reason"),
                **record_attributes(record),
            }
            if record
            else {}
        )


class IdentitySensor(TallyEntity, SensorEntity):
    def __init__(
        self, runtime: Runtime, id_: str, name: str, period: str, metric: str
    ) -> None:
        super().__init__(
            runtime,
            id_,
            period + "_" + metric,
            name + " " + period + " " + metric,
            name,
        )
        self.period, self.metric = period, metric
        self._attr_suggested_display_precision = 3 if metric == "energy" else 2
        self._attr_native_unit_of_measurement = (
            "kWh" if metric == "energy" else runtime.entry.data["currency"]
        )
        self._attr_state_class = SensorStateClass.TOTAL

    @property
    def last_reset(self) -> datetime | None:
        """Reset calendar totals only when their published snapshot rolls over."""
        start = self.runtime.snapshot.get("period_starts", {}).get(self.period)
        return datetime.fromisoformat(start) if start is not None else None

    @property
    def summary(self) -> dict[str, Any] | None:
        identity = next(
            (i for i in self.runtime.snapshot["identities"] if i["id"] == self.id_),
            None,
        )
        return identity.get("summaries", {}).get(self.period) if identity else None

    @property
    def native_value(self) -> str | None:
        return (
            self.summary["energy_kwh" if self.metric == "energy" else "known_cost"]
            if self.summary
            else None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return (
            {
                "known_cost": self.summary["known_cost"],
                "has_known_cost": self.summary["has_known_cost"],
                "cost_complete": self.summary["cost_complete"],
                "quality": self.summary["quality"],
            }
            if self.summary
            else {}
        )
