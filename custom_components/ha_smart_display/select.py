from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import WAKE_WORD_OPTIONS
from .entity_base import HaSmartDisplayEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities([
        WakeWordSelect(hass, entry),
    ])


class WakeWordSelect(HaSmartDisplayEntity, SelectEntity):
    _attr_name = "Wake Word"
    _attr_icon = "mdi:microphone"
    _attr_options = WAKE_WORD_OPTIONS

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


