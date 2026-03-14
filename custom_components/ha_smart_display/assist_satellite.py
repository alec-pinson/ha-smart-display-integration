import logging

from homeassistant.components.assist_pipeline import PipelineEvent, PipelineEventType
from homeassistant.components.assist_satellite import (
    AssistSatelliteConfiguration,
    AssistSatelliteEntity,
    AssistSatelliteEntityFeature,
    AssistSatelliteWakeWord,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.network import get_url

from .const import DOMAIN, WAKE_WORD_OPTIONS
from .entity_base import HaSmartDisplayEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entity = HaSmartDisplayAssistSatellite(hass, entry)
    async_add_entities([entity])
    device_id = entry.data["device_id"]
    hass.data[DOMAIN][device_id]["satellite_entity"] = entity


class HaSmartDisplayAssistSatellite(HaSmartDisplayEntity, AssistSatelliteEntity):
    _attr_name = "Assist"
    _attr_icon = "mdi:microphone-message"
    _attr_supported_features = AssistSatelliteEntityFeature(0)

    @property
    def entity_description_key(self):
        return "assist_satellite"

    def _handle_state_update(self, payload: dict) -> None:
        pass

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._last_intent_text: str = ""

    @callback
    def async_get_configuration(self) -> AssistSatelliteConfiguration:
        current = self._current_state().get("wake_word", "alexa")
        return AssistSatelliteConfiguration(
            available_wake_words=[
                AssistSatelliteWakeWord(
                    id=ww,
                    wake_word=ww,
                    trained_languages=["en"],
                )
                for ww in WAKE_WORD_OPTIONS
            ],
            active_wake_words=[current],
            max_active_wake_words=1,
        )

    async def async_set_configuration(
        self, config: AssistSatelliteConfiguration
    ) -> None:
        if config.active_wake_words:
            self._send_command({"wake_word": config.active_wake_words[0]})

    def on_pipeline_event(self, event: PipelineEvent) -> None:
        if event.type == PipelineEventType.INTENT_END and event.data:
            try:
                self._last_intent_text = (
                    event.data["intent_output"]["response"]["speech"]["plain"]["speech"]
                )
            except (KeyError, TypeError):
                self._last_intent_text = ""

        elif event.type == PipelineEventType.TTS_END and event.data:
            tts_url = event.data.get("tts_output", {}).get("url")
            if tts_url and tts_url.startswith("/"):
                try:
                    base = get_url(self.hass, allow_internal=True, prefer_external=False)
                    tts_url = f"{base.rstrip('/')}{tts_url}"
                except Exception as exc:
                    _LOGGER.warning("ha_smart_display: could not resolve TTS URL: %s", exc)
                    tts_url = None
            self._send_command({
                "voice_response": {
                    "text": self._last_intent_text,
                    "tts_url": tts_url,
                }
            })
            self._last_intent_text = ""

        elif event.type == PipelineEventType.ERROR and event.data:
            _LOGGER.warning(
                "ha_smart_display: pipeline error: %s",
                event.data.get("message", "unknown"),
            )

    def on_tts_finished(self) -> None:
        """Signal that the device has finished playing TTS audio."""
        self.tts_response_finished()
