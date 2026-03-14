from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import WAKE_WORD_OPTIONS, WAKE_WORD_SENSITIVITY_OPTIONS, VAD_SENSITIVITY_OPTIONS, AMBIENT_MODE_OPTIONS
from .entity_base import HaSmartDisplayEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities([
        WakeWordSelect(hass, entry),
        WakeWordSensitivitySelect(hass, entry),
        VadSensitivitySelect(hass, entry),
        AmbientModeSelect(hass, entry),
    ])


class WakeWordSelect(HaSmartDisplayEntity, SelectEntity):
    _attr_name = "Wake Word"
    _attr_icon = "mdi:microphone"
    _attr_options = WAKE_WORD_OPTIONS
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def entity_description_key(self):
        return "wake_word"

    @property
    def current_option(self):
        return self._current_state().get("wake_word", WAKE_WORD_OPTIONS[0])

    def _handle_state_update(self, payload):
        self.async_write_ha_state()

    async def async_select_option(self, option: str):
        self._send_command({"wake_word": option})


class WakeWordSensitivitySelect(HaSmartDisplayEntity, SelectEntity):
    _attr_name = "Wake Word Sensitivity"
    _attr_icon = "mdi:microphone-settings"
    _attr_options = WAKE_WORD_SENSITIVITY_OPTIONS
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def entity_description_key(self):
        return "wake_word_sensitivity"

    @property
    def current_option(self):
        return self._current_state().get("wake_word_sensitivity", "medium")

    def _handle_state_update(self, payload):
        self.async_write_ha_state()

    async def async_select_option(self, option: str):
        self._send_command({"wake_word_sensitivity": option})


class VadSensitivitySelect(HaSmartDisplayEntity, SelectEntity):
    _attr_name = "Finished Speaking Detection"
    _attr_icon = "mdi:waveform"
    _attr_options = VAD_SENSITIVITY_OPTIONS
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def entity_description_key(self):
        return "vad_sensitivity"

    @property
    def current_option(self):
        return self._current_state().get("vad_sensitivity", "default")

    def _handle_state_update(self, payload):
        self.async_write_ha_state()

    async def async_select_option(self, option: str):
        self._send_command({"vad_sensitivity": option})


class AmbientModeSelect(HaSmartDisplayEntity, SelectEntity):
    _attr_name = "Display Mode"
    _attr_icon = "mdi:television-ambient-light"
    _attr_options = AMBIENT_MODE_OPTIONS

    @property
    def entity_description_key(self):
        return "ambient_mode"

    @property
    def current_option(self):
        return self._current_state().get("ambient_mode", "clock")

    def _handle_state_update(self, payload):
        self.async_write_ha_state()

    async def async_select_option(self, option: str):
        self._send_command({"ambient_mode": option})
