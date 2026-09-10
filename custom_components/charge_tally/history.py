"""Bounded, read-only Recorder access preserving actual sample timestamps."""
from datetime import timedelta
from functools import partial

from .accounting import instant
from .core.units import energy_kwh, price_per_kwh


class HistorySource:
    def __init__(self, hass):
        self.hass = hass

    async def _states(self, entity_id, start, end):
        from homeassistant.components.recorder import get_instance, history
        if not entity_id:
            raise ValueError("An explicit source entity is required")
        try:
            recorder = get_instance(self.hass)
        except KeyError:
            return []
        result = await recorder.async_add_executor_job(partial(history.get_significant_states, self.hass,
            instant(start), instant(end), entity_ids=[entity_id], include_start_time_state=False,
            significant_changes_only=False, minimal_response=False, no_attributes=False,
            compressed_state_format=False))
        return sorted(result.get(entity_id, []), key=lambda state: state.last_updated)

    async def async_intervals(self, entity_id, start, end, resetting, max_gap_seconds):
        start, end = instant(start), instant(end)
        if end <= start or max_gap_seconds <= 0:
            raise ValueError("A positive history range and maximum gap are required")
        margin = timedelta(seconds=max_gap_seconds)
        states = await self._states(entity_id, start - margin, end + margin + timedelta(microseconds=1))
        result, previous, interrupted = [], None, False
        for state in states:
            at = instant(state.last_updated)
            try:
                if state.attributes.get("state_class") not in ("total", "total_increasing"):
                    raise ValueError("Cumulative source required")
                value = energy_kwh(state.state, state.attributes.get("unit_of_measurement"))
            except ValueError:
                interrupted = True
                continue
            if previous and at > previous[0]:
                left, old = previous
                delta = value - old
                quality = ["unavailable"] if interrupted else []
                if delta < 0:
                    quality.append("reset")
                    delta = value if resetting else None
                if (at - left).total_seconds() > max_gap_seconds:
                    quality.append("gap")
                if left < end and at > start and delta is not None:
                    result.append({"start": left.isoformat(), "end": at.isoformat(), "energy_kwh": str(delta),
                                   "quality": quality, "source": "recorder", "gap": bool(quality)})
            previous, interrupted = (at, value), False
        return result

    async def async_prices(self, entity_id, start, end, currency, unit):
        from homeassistant.components.recorder import get_instance, history
        start, end = instant(start), instant(end)
        try:
            recorder = get_instance(self.hass)
        except KeyError:
            return [(start, None)]
        result = await recorder.async_add_executor_job(partial(history.get_significant_states, self.hass,
            start - timedelta(microseconds=1), end, entity_ids=[entity_id], include_start_time_state=True,
            significant_changes_only=False, minimal_response=False, no_attributes=False, compressed_state_format=False))
        timeline = {start: None}
        for state in result.get(entity_id, []):
            try:
                value = price_per_kwh(state.state, state.attributes.get("unit_of_measurement") or unit, currency)
            except ValueError:
                value = None
            timeline[max(start, instant(state.last_updated))] = value
        return sorted(timeline.items())
