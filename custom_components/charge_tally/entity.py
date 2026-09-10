"""Memory-only entity base and dynamic subentry discovery."""
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity


class TallyEntity(Entity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, runtime, id_, key, name):
        self.runtime, self.id_ = runtime, id_
        self._attr_unique_id = runtime.entry.entry_id + ":" + id_ + ":" + key
        self._attr_name = name

    @property
    def point(self):
        return next((p for p in self.runtime.snapshot["points"] if p["id"] == self.id_), None)

    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(self.hass, self.runtime.update_signal, self._updated))

    @callback
    def _updated(self):
        self.async_write_ha_state()


def setup_entities(hass, entry, async_add_entities, factory):
    runtime, known = entry.runtime_data, set()

    @callback
    def discover():
        for subentry in entry.subentries.values():
            if subentry.subentry_id in known:
                continue
            entities = factory(runtime, subentry)
            if entities:
                async_add_entities(entities, config_subentry_id=subentry.subentry_id)
            known.add(subentry.subentry_id)

    entry.async_on_unload(async_dispatcher_connect(hass, runtime.config_signal, discover))
    discover()
