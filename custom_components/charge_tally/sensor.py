"""Live cumulative energy and record state entities."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass

from .entity import TallyEntity, setup_entities


async def async_setup_entry(hass, entry, async_add_entities):
    def factory(runtime, sub):
        if sub.subentry_type == "point":
            return [Energy(runtime, sub), Status(runtime, sub), RecordSensor(runtime, sub, "energy"), RecordSensor(runtime, sub, "cost")]
        return [IdentitySensor(runtime, sub.subentry_id, sub.data["name"], period, metric)
                for period in ("daily", "monthly", "yearly", "total") for metric in ("energy", "cost")]
    await setup_entities(hass, entry, async_add_entities, factory)
    async_add_entities([IdentitySensor(entry.runtime_data, "unassigned", "Unassigned", period, metric)
                        for period in ("daily", "monthly", "yearly", "total") for metric in ("energy", "cost")])


class Energy(TallyEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, runtime, sub):
        super().__init__(runtime, sub.subentry_id, "energy", sub.data["name"] + " Energy")

    @property
    def native_value(self):
        return self.point["normalized_energy_kwh"] if self.point else None


class Status(TallyEntity, SensorEntity):
    def __init__(self, runtime, sub):
        super().__init__(runtime, sub.subentry_id, "status", sub.data["name"] + " Status")

    @property
    def native_value(self):
        return self.point["status"] if self.point else None

    @property
    def extra_state_attributes(self):
        return {"quality": self.point["quality"], "error": self.point.get("error")} if self.point else {}


class RecordSensor(TallyEntity, SensorEntity):
    def __init__(self, runtime, sub, metric):
        super().__init__(runtime, sub.subentry_id, "record_" + metric, sub.data["name"] + " Record " + metric)
        self.metric = metric
        self._attr_native_unit_of_measurement = "kWh" if metric == "energy" else runtime.entry.data["currency"]

    @property
    def native_value(self):
        record = self.point.get("active_record") if self.point else None
        if record and self.metric == "cost" and not record["cost_complete"]:
            return None
        return record["energy_kwh" if self.metric == "energy" else "known_cost"] if record else None

    @property
    def extra_state_attributes(self):
        record = self.point.get("active_record") if self.point else None
        return {"known_cost": record["known_cost"], "cost_complete": record["cost_complete"], "quality": record["quality"]} if record else {}


class IdentitySensor(TallyEntity, SensorEntity):
    def __init__(self, runtime, id_, name, period, metric):
        super().__init__(runtime, id_, period + "_" + metric, name + " " + period + " " + metric)
        self.period, self.metric = period, metric
        self._attr_native_unit_of_measurement = "kWh" if metric == "energy" else runtime.entry.data["currency"]
        self._attr_state_class = SensorStateClass.TOTAL

    @property
    def summary(self):
        identity = next((i for i in self.runtime.snapshot["identities"] if i["id"] == self.id_), None)
        return identity.get("summaries", {}).get(self.period) if identity else None

    @property
    def native_value(self):
        if self.summary and self.metric == "cost" and not self.summary["cost_complete"]:
            return None
        return self.summary["energy_kwh" if self.metric == "energy" else "known_cost"] if self.summary else None

    @property
    def extra_state_attributes(self):
        return {"known_cost": self.summary["known_cost"], "cost_complete": self.summary["cost_complete"], "quality": self.summary["quality"]} if self.summary else {}
