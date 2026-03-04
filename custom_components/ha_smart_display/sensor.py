from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_base import HaSmartDisplayEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities([
        UptimeSensor(hass, entry),
        WakeWordCountSensor(hass, entry),
    ])


class UptimeSensor(HaSmartDisplayEntity, SensorEntity):
    _attr_name = "Uptime"
    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = "s"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def entity_description_key(self):
        return "uptime"

    @property
    def native_value(self):
        return self._current_state().get("uptime_seconds", 0)

    def _handle_state_update(self, payload):
        self.async_write_ha_state()


class WakeWordCountSensor(HaSmartDisplayEntity, SensorEntity):
    _attr_name = "Wake Word Count"
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def entity_description_key(self):
        return "wake_word_count"

    @property
    def native_value(self):
        return self._current_state().get("wake_word_count", 0)

    def _handle_state_update(self, payload):
        self.async_write_ha_state()
