from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import LIGHT_LUX, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_base import HaSmartDisplayEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities([
        UptimeSensor(hass, entry),
        WakeWordCountSensor(hass, entry),
        LuxSensor(hass, entry),
        MemorySensor(hass, entry),
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


class LuxSensor(HaSmartDisplayEntity, SensorEntity):
    _attr_name = "Illuminance"
    _attr_icon = "mdi:brightness-5"
    _attr_device_class = SensorDeviceClass.ILLUMINANCE
    _attr_native_unit_of_measurement = LIGHT_LUX
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def entity_description_key(self):
        return "lux"

    @property
    def native_value(self):
        val = self._current_state().get("lux")
        if val is None:
            return None
        return round(float(val), 1)

    def _handle_state_update(self, payload):
        self.async_write_ha_state()


class MemorySensor(HaSmartDisplayEntity, SensorEntity):
    _attr_name = "Memory Usage"
    _attr_icon = "mdi:memory"
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 0

    @property
    def entity_description_key(self):
        return "memory_mb"

    @property
    def native_value(self):
        val = self._current_state().get("memory_mb")
        if val is None:
            return None
        return int(val)

    def _handle_state_update(self, payload):
        self.async_write_ha_state()
