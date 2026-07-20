import logging

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity_base import HaSmartDisplayEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities([ScreenCamera(hass, entry)])


class ScreenCamera(HaSmartDisplayEntity, Camera):
    """Serves the most recent screenshot captured from the display.

    Deliberately passive: viewing this entity never triggers a capture. Home
    Assistant builds a still-stream by calling `async_camera_image` at
    `frame_interval`, which defaults to 0.5s — capturing at 2fps on a 1GB
    device would trip the memory watchdog. Capture is explicitly triggered by
    the Take Screenshot button or the take_screenshot service.
    """

    _attr_name = "Screen"
    _attr_icon = "mdi:monitor-screenshot"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        HaSmartDisplayEntity.__init__(self, hass, entry)
        Camera.__init__(self)

    @property
    def entity_description_key(self):
        return "screen"

    @property
    def frame_interval(self) -> float:
        # Discourage HA from polling for a still-stream. Nothing here is live.
        return 3600.0

    def _slot(self) -> dict:
        return self.hass.data.get(DOMAIN, {}).get(self._device_id, {})

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        # Returns None until the first capture, which HA renders as a
        # placeholder rather than an error.
        return self._slot().get("screenshot")

    @property
    def extra_state_attributes(self):
        captured_at = self._slot().get("screenshot_at")
        return {"last_captured": captured_at.isoformat() if captured_at else None}

    def _handle_state_update(self, payload: dict) -> None:
        # Refresh the last_captured attribute when a new screenshot lands.
        self.async_write_ha_state()
