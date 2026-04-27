import logging

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity_base import HaSmartDisplayEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities([AppUpdateEntity(hass, entry)])


class AppUpdateEntity(HaSmartDisplayEntity, UpdateEntity):
    _attr_name = "App"
    _attr_title = "HA Smart Display App"
    _attr_supported_features = UpdateEntityFeature.INSTALL

    @property
    def entity_description_key(self):
        return "app_update"

    @property
    def installed_version(self) -> str | None:
        return (
            self.hass.data.get(DOMAIN, {})
            .get(self._device_id, {})
            .get("app_version")
        )

    @property
    def latest_version(self) -> str | None:
        updater = self.hass.data.get(DOMAIN, {}).get(self._device_id, {}).get("updater")
        return updater.latest_version if updater else None

    @property
    def release_url(self) -> str | None:
        updater = self.hass.data.get(DOMAIN, {}).get(self._device_id, {}).get("updater")
        return updater.release_html_url if updater else None

    def _handle_state_update(self, payload: dict) -> None:
        self.async_write_ha_state()

    async def async_install(self, version: str | None, backup: bool, **kwargs) -> None:
        updater = self.hass.data.get(DOMAIN, {}).get(self._device_id, {}).get("updater")
        apk_url = updater.latest_apk_url if updater else None
        if not updater or not apk_url:
            _LOGGER.warning("ha_smart_display: no APK URL available, cannot install update")
            return
        _LOGGER.debug("ha_smart_display: sending ota_update, url=%s", apk_url)
        self._send_command({"action": "ota_update", "url": apk_url})
