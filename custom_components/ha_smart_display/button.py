from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_base import HaSmartDisplayEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities([
        RestartButton(hass, entry),
        NextPhotoButton(hass, entry),
        PreviousPhotoButton(hass, entry),
    ])


class RestartButton(HaSmartDisplayEntity, ButtonEntity):
    _attr_name = "Restart"
    _attr_icon = "mdi:restart"

    @property
    def entity_description_key(self):
        return "restart"

    def _handle_state_update(self, payload):
        pass

    async def async_press(self):
        self._send_command({"action": "restart"})


class NextPhotoButton(HaSmartDisplayEntity, ButtonEntity):
    _attr_name = "Next Photo"
    _attr_icon = "mdi:skip-next"

    @property
    def entity_description_key(self):
        return "next_photo"

    def _handle_state_update(self, payload):
        pass

    async def async_press(self):
        self._send_command({"photo_command": "next"})


class PreviousPhotoButton(HaSmartDisplayEntity, ButtonEntity):
    _attr_name = "Previous Photo"
    _attr_icon = "mdi:skip-previous"

    @property
    def entity_description_key(self):
        return "previous_photo"

    def _handle_state_update(self, payload):
        pass

    async def async_press(self):
        self._send_command({"photo_command": "previous"})
