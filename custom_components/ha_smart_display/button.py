from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_STATE_UPDATED
from .entity_base import HaSmartDisplayEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities([
        RestartButton(hass, entry),
        NextPhotoButton(hass, entry),
        PreviousPhotoButton(hass, entry),
        WakeForVoiceButton(hass, entry),
        CheckForUpdatesButton(hass, entry),
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


class WakeForVoiceButton(HaSmartDisplayEntity, ButtonEntity):
    _attr_name = "Wake for Voice"
    _attr_icon = "mdi:microphone"

    @property
    def entity_description_key(self):
        return "wake_for_voice"

    def _handle_state_update(self, payload):
        pass

    async def async_press(self):
        self._send_command({"action": "wake_for_voice"})


class CheckForUpdatesButton(HaSmartDisplayEntity, ButtonEntity):
    _attr_name = "Check for Updates"
    _attr_icon = "mdi:update"

    @property
    def entity_description_key(self):
        return "check_for_updates"

    def _handle_state_update(self, payload):
        pass

    async def async_press(self):
        updater = self.hass.data.get(DOMAIN, {}).get(self._device_id, {}).get("updater")
        if updater:
            await updater.async_check()
            async_dispatcher_send(
                self.hass,
                SIGNAL_STATE_UPDATED.format(device_id=self._device_id),
                {},
            )
