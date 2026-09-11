"""Memory-only entity base and dynamic subentry discovery."""
import asyncio

from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity


class TallyEntity(Entity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, runtime, id_, key, legacy_name, owner_name):
        self.runtime, self.id_ = runtime, id_
        self._attr_unique_id = runtime.entry.entry_id + ":" + id_ + ":" + key
        self._attr_translation_key = key
        self._attr_translation_placeholders = {"name": owner_name}
        self._legacy_name = legacy_name

    @property
    def suggested_object_id(self):
        """Keep the original object ID format independent of display language."""
        return self._legacy_name

    @property
    def point(self):
        return next((p for p in self.runtime.snapshot["points"] if p["id"] == self.id_), None)

    async def async_added_to_hass(self):
        # Older HA versions drop the subentry when re-adding a renamed entity.
        registry = er.async_get(self.hass)
        registered = registry.async_get(self.entity_id)
        entry = self.runtime.entry
        if (registered is not None and registered.config_subentry_id is None
                and registered.platform == "charge_tally"
                and registered.config_entry_id == entry.entry_id
                and registered.unique_id == self.unique_id
                and self.id_ in entry.subentries and not registered.disabled):
            self.registry_entry = registry.async_update_entity(
                self.entity_id, config_subentry_id=self.id_)
        self.async_on_remove(async_dispatcher_connect(self.hass, self.runtime.update_signal, self._updated))

    @callback
    def _updated(self):
        self.async_write_ha_state()


async def setup_entities(hass, entry, async_add_entities, factory):
    runtime, known, lock = entry.runtime_data, {}, asyncio.Lock()

    async def reconcile():
        async with lock:
            desired = {entity.unique_id: (entity, subentry.subentry_id)
                       for subentry in entry.subentries.values() for entity in factory(runtime, subentry)}
            registry = er.async_get(hass)
            for unique_id in list(known):
                if unique_id in desired:
                    continue
                entity, subentry_id = known.pop(unique_id)
                if entity.hass is not None:
                    await entity.async_remove(force_remove=True)
                for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
                    if registered.platform == "charge_tally" and registered.unique_id == unique_id and registered.config_subentry_id == subentry_id:
                        registry.async_remove(registered.entity_id)
            for unique_id, (entity, subentry_id) in desired.items():
                if unique_id not in known:
                    async_add_entities([entity], config_subentry_id=subentry_id)
                    known[unique_id] = (entity, subentry_id)

    @callback
    def discover():
        runtime._queue(reconcile())

    entry.async_on_unload(async_dispatcher_connect(hass, runtime.config_signal, discover))
    await reconcile()
