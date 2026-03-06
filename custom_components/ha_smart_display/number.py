from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_base import HaSmartDisplayEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities([BrightnessEntity(hass, entry), VolumeEntity(hass, entry)])


class BrightnessEntity(HaSmartDisplayEntity, NumberEntity):
    _attr_name = "Brightness"
    _attr_icon = "mdi:brightness-6"
    _attr_native_min_value = 10  # values below 10/255 fall back to system brightness on Android
    _attr_native_max_value = 255
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    @property
    def entity_description_key(self):
        return "brightness"

    @property
    def native_value(self):
        return self._current_state().get("brightness", 128)

    def _handle_state_update(self, payload):
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float):
        self._send_command({"brightness": int(value)})


class VolumeEntity(HaSmartDisplayEntity, NumberEntity):
    _attr_name = "Volume"
    _attr_icon = "mdi:volume-high"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    @property
    def entity_description_key(self):
        return "volume"

    @property
    def native_value(self):
        return self._current_state().get("volume", 50)

    def _handle_state_update(self, payload):
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float):
        self._send_command({"volume": int(value)})
