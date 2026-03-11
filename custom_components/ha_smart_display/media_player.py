from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    MEDIA_STATE_IDLE,
    MEDIA_STATE_PLAYING,
    MEDIA_STATE_PAUSED,
)
from .entity_base import HaSmartDisplayEntity

_LOGGER = logging.getLogger(__name__)

_STATE_MAP = {
    MEDIA_STATE_IDLE: MediaPlayerState.IDLE,
    MEDIA_STATE_PLAYING: MediaPlayerState.PLAYING,
    "buffering": MediaPlayerState.PLAYING,
    MEDIA_STATE_PAUSED: MediaPlayerState.PAUSED,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([HaSmartDisplayMediaPlayer(hass, entry)])


class HaSmartDisplayMediaPlayer(HaSmartDisplayEntity, MediaPlayerEntity):
    entity_description_key = "media_player"
    _attr_name = "Media Player"
    _attr_media_content_type = MediaType.MUSIC
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.SEEK
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
    )

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._media_player_state = MediaPlayerState.IDLE
        self._media_title: str | None = None
        self._media_artist: str | None = None
        self._media_album: str | None = None
        self._entity_picture_url: str | None = None
        self._media_duration: float | None = None
        self._media_position: float | None = None
        self._media_position_updated_at: datetime | None = None

    @property
    def state(self) -> MediaPlayerState:
        return self._media_player_state

    @property
    def media_title(self) -> str | None:
        return self._media_title

    @property
    def media_artist(self) -> str | None:
        return self._media_artist

    @property
    def media_album_name(self) -> str | None:
        return self._media_album

    @property
    def entity_picture(self) -> str | None:
        return self._entity_picture_url

    @property
    def media_duration(self) -> float | None:
        return self._media_duration

    @property
    def media_position(self) -> float | None:
        return self._media_position

    @property
    def media_position_updated_at(self) -> datetime | None:
        return self._media_position_updated_at

    @property
    def volume_level(self) -> float | None:
        vol = self._current_state().get("volume")
        return vol / 100 if vol is not None else None

    def _handle_state_update(self, payload: dict) -> None:
        media_state_str = payload.get("media_state", MEDIA_STATE_IDLE)
        self._media_player_state = _STATE_MAP.get(media_state_str, MediaPlayerState.IDLE)

        track = payload.get("media_track")
        if track:
            self._media_title = track.get("title")
            self._media_artist = track.get("artist")
            self._media_album = track.get("album")
            self._entity_picture_url = track.get("art_url")
            duration_ms = track.get("duration_ms")
            self._media_duration = duration_ms / 1000 if duration_ms else None
            position_ms = track.get("position_ms")
            if position_ms is not None:
                self._media_position = position_ms / 1000
                self._media_position_updated_at = dt_util.utcnow()
        else:
            self._media_title = None
            self._media_artist = None
            self._media_album = None
            self._entity_picture_url = None
            self._media_duration = None
            self._media_position = None
            self._media_position_updated_at = None

        self.async_write_ha_state()

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs
    ) -> None:
        # Resolve media-source:// URIs (used by tts.speak in modern HA) to HTTP URLs
        if media_id.startswith("media-source://"):
            try:
                from homeassistant.components import media_source
                resolved = await media_source.async_resolve_media(self.hass, media_id, None)
                media_id = resolved.url
                _LOGGER.debug("ha_smart_display: resolved media-source to: %s", media_id)
            except Exception as e:
                _LOGGER.warning("ha_smart_display: could not resolve media-source URI: %s", e)

        # Resolve relative URLs (e.g. /api/tts_proxy/...) to absolute so the
        # device can fetch them directly from the HA server
        if media_id.startswith("/"):
            try:
                from homeassistant.helpers.network import get_url
                base = get_url(self.hass, allow_internal=True, prefer_external=False)
                media_id = f"{base.rstrip('/')}{media_id}"
            except Exception as e:
                _LOGGER.warning("ha_smart_display: could not resolve media URL: %s", e)

        _LOGGER.debug("ha_smart_display: play_media url=%s type=%s", media_id, media_type)

        extra = kwargs.get("extra") or {}
        _LOGGER.debug("ha_smart_display: play_media extra=%s", extra)
        # MA nests metadata under extra["metadata"] with camelCase keys
        meta = extra.get("metadata") or {}
        images = meta.get("images") or []
        title = meta.get("title") or extra.get("title") or extra.get("media_title") or ""
        artist = meta.get("artist") or extra.get("artist") or extra.get("media_artist")
        album = meta.get("album") or meta.get("albumName") or extra.get("album") or extra.get("media_album") or extra.get("album_name")
        duration_raw = meta.get("duration") or extra.get("duration") or extra.get("duration_ms") or 0
        # MA sends duration in seconds; convert to ms
        duration_ms = int(duration_raw * 1000) if duration_raw < 100000 else int(duration_raw)
        art_url = (
            meta.get("imageUrl")
            or (images[0].get("url") if images else None)
            or extra.get("art_url")
            or extra.get("image_url")
            or extra.get("image")
        )
        # Resolve relative art URLs (e.g. /api/...) to absolute so the device can fetch them
        if art_url and art_url.startswith("/"):
            try:
                from homeassistant.helpers.network import get_url
                base = get_url(self.hass, allow_internal=True, prefer_external=False)
                art_url = f"{base.rstrip('/')}{art_url}"
            except Exception as e:
                _LOGGER.warning("ha_smart_display: could not resolve art URL: %s", e)
        # If an MA media player is configured, it will push the real track info via
        # media_track command immediately after. Send empty metadata here so the device
        # keeps the current track displayed rather than flashing a generic placeholder.
        from . import get_connection
        conn = get_connection(self.hass, self._device_id)
        if conn and getattr(conn, "_ma_media_player", None):
            title, artist, album, art_url = "", None, None, None
        payload = {
            "play_media": {
                "url": media_id,
                "title": title,
                "artist": artist,
                "album": album,
                "art_url": art_url,
                "duration_ms": duration_ms,
            }
        }
        self._send_command(payload)

    async def async_media_pause(self) -> None:
        self._send_command({"media_command": "pause"})

    async def async_media_play(self) -> None:
        self._send_command({"media_command": "play"})

    async def async_media_stop(self) -> None:
        self._send_command({"media_command": "stop"})

    async def async_media_next_track(self) -> None:
        self._send_command({"media_command": "next"})

    async def async_media_previous_track(self) -> None:
        self._send_command({"media_command": "previous"})

    async def async_set_volume_level(self, volume: float) -> None:
        self._send_command({"volume": int(volume * 100)})

    async def async_media_seek(self, position: float) -> None:
        self._send_command({"media_command": "seek", "position_ms": int(position * 1000)})
