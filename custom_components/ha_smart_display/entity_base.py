import logging
from abc import abstractmethod

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, CONF_DEVICE_ID, CONF_DEVICE_NAME, SIGNAL_STATE_UPDATED, SIGNAL_AVAILABILITY_UPDATED
from . import get_connection

_LOGGER = logging.getLogger(__name__)


class HaSmartDisplayEntity(Entity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._device_id = entry.data[CONF_DEVICE_ID]
        self._device_name = entry.data[CONF_DEVICE_NAME]

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "Amazon",
            "model": "Echo Show 8",
        }

    @property
    def unique_id(self):
        key = getattr(self, "entity_description_key", self.__class__.__name__)
        return f"{self._device_id}_{key}"

    @property
    def available(self):
        return (
            self.hass.data.get(DOMAIN, {})
            .get(self._device_id, {})
            .get("available", False)
        )

    def _current_state(self) -> dict:
        return (
            self.hass.data.get(DOMAIN, {})
            .get(self._device_id, {})
            .get("state", {})
        )

    def _send_command(self, payload: dict):
        conn = get_connection(self.hass, self._device_id)
        if conn:
            self.hass.async_create_task(conn.send_command(payload))

    @abstractmethod
    def _handle_state_update(self, payload: dict) -> None:
        pass

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_STATE_UPDATED.format(device_id=self._device_id),
                self._on_state_updated,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_AVAILABILITY_UPDATED.format(device_id=self._device_id),
                self._on_availability_updated,
            )
        )

    @callback
    def _on_state_updated(self, payload: dict) -> None:
        self._handle_state_update(payload)

    @callback
    def _on_availability_updated(self, available: bool) -> None:
        self.async_write_ha_state()
