import asyncio
import base64
import json
import logging
from datetime import datetime

import websockets

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    DOMAIN,
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_PORT,
    CONF_WEATHER_ENTITY,
    CONF_PHOTO_URLS,
    CONF_CAMERA_ENTITIES,
    CONF_CLIMATE_ENTITY,
    CONF_TEMPERATURE_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_AUTO_AMBIENT_LUX,
    CONF_MA_MEDIA_PLAYER,
    CONF_DOOR_ENTITIES,
    CONF_MOTION_ENTITIES,
    SIGNAL_STATE_UPDATED,
    SIGNAL_AVAILABILITY_UPDATED,
    SERVICE_SET_TIMER,
    SERVICE_DISMISS_TIMER,
    SERVICE_SET_ALARM,
    SERVICE_DISMISS_ALARM,
    SERVICE_SET_PHOTOS,
    SERVICE_SEND_NOTIFICATION,
    SERVICE_OPEN_CAMERA,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["select", "switch", "number", "button", "sensor", "media_player"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    device_id = entry.data[CONF_DEVICE_ID]
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    weather_entity = entry.options.get(CONF_WEATHER_ENTITY) or entry.data.get(CONF_WEATHER_ENTITY)
    photo_urls = _parse_photo_urls(entry.options.get(CONF_PHOTO_URLS, ""))
    camera_entities = entry.options.get(CONF_CAMERA_ENTITIES, [])
    climate_entity = entry.options.get(CONF_CLIMATE_ENTITY) or entry.data.get(CONF_CLIMATE_ENTITY)
    temperature_sensor = entry.options.get(CONF_TEMPERATURE_SENSOR) or None
    humidity_sensor = entry.options.get(CONF_HUMIDITY_SENSOR) or None
    auto_ambient_lux = entry.options.get(CONF_AUTO_AMBIENT_LUX) or None
    ma_media_player = entry.options.get(CONF_MA_MEDIA_PLAYER) or None
    door_entities = entry.options.get(CONF_DOOR_ENTITIES, [])
    motion_entities = entry.options.get(CONF_MOTION_ENTITIES, [])

    hass.data.setdefault(DOMAIN, {})[device_id] = {
        "state": {},
        "available": False,
        "connection": None,
        "timers": {},
        "alarms": {},
        "photos": photo_urls,
    }

    connection = DeviceConnection(hass, entry, device_id, host, port, weather_entity, camera_entities, climate_entity, temperature_sensor, humidity_sensor, auto_ambient_lux, ma_media_player, door_entities, motion_entities)
    hass.data[DOMAIN][device_id]["connection"] = connection
    entry.async_on_unload(connection.stop)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_create_background_task(
        hass, connection.run(), f"ha_smart_display_{device_id}"
    )

    # Register services
    _register_services(hass)

    # Listen for options updates (weather entity change)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — reconnect with new weather entity."""
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    import voluptuous as vol
    import homeassistant.helpers.config_validation as cv

    if hass.services.has_service(DOMAIN, SERVICE_SET_TIMER):
        return

    async def handle_set_timer(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        conn = get_connection(hass, device_id)
        if not conn:
            return
        duration = call.data["duration_seconds"]
        ends_at = int(datetime.now().timestamp()) + duration
        timer = {
            "id": call.data["timer_id"],
            "label": call.data.get("label", "Timer"),
            "duration_seconds": duration,
            "ends_at": ends_at,
        }
        hass.data[DOMAIN][device_id]["timers"][timer["id"]] = timer
        now = int(datetime.now().timestamp())
        timers_with_remaining = [
            {**t, "remaining_seconds": max(0, t["ends_at"] - now)}
            for t in hass.data[DOMAIN][device_id]["timers"].values()
        ]
        await conn.send_command({"timers": timers_with_remaining})

    async def handle_dismiss_timer(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        timer_id = call.data["timer_id"]
        conn = get_connection(hass, device_id)
        hass.data[DOMAIN][device_id]["timers"].pop(timer_id, None)
        if conn:
            await conn.send_command({"timers": list(hass.data[DOMAIN][device_id]["timers"].values())})

    async def handle_set_alarm(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        conn = get_connection(hass, device_id)
        if not conn:
            return
        alarm = {
            "id": call.data["alarm_id"],
            "label": call.data.get("label", "Alarm"),
            "time": call.data["time"],  # "HH:MM"
        }
        hass.data[DOMAIN][device_id]["alarms"][alarm["id"]] = alarm
        await conn.send_command({"alarms": list(hass.data[DOMAIN][device_id]["alarms"].values())})

    async def handle_dismiss_alarm(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        alarm_id = call.data["alarm_id"]
        conn = get_connection(hass, device_id)
        hass.data[DOMAIN][device_id]["alarms"].pop(alarm_id, None)
        if conn:
            await conn.send_command({"alarms": list(hass.data[DOMAIN][device_id]["alarms"].values())})

    hass.services.async_register(
        DOMAIN, SERVICE_SET_TIMER, handle_set_timer,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("timer_id"): cv.string,
            vol.Required("duration_seconds"): vol.Coerce(int),
            vol.Optional("label", default="Timer"): cv.string,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISMISS_TIMER, handle_dismiss_timer,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("timer_id"): cv.string,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_ALARM, handle_set_alarm,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("alarm_id"): cv.string,
            vol.Required("time"): cv.string,
            vol.Optional("label", default="Alarm"): cv.string,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISMISS_ALARM, handle_dismiss_alarm,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("alarm_id"): cv.string,
        }),
    )

    async def handle_set_photos(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        urls = call.data.get("urls", [])
        conn = get_connection(hass, device_id)
        hass.data[DOMAIN][device_id]["photos"] = urls
        if conn:
            await conn.send_command({"photos": urls})

    async def handle_send_notification(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        conn = get_connection(hass, device_id)
        if not conn:
            return
        notification = {
            "title": call.data.get("title", ""),
            "message": call.data.get("message", ""),
            "image_url": call.data.get("image_url"),
            "duration": call.data.get("duration", 10),
            "buttons": call.data.get("buttons", []),
            "style": call.data.get("style", "dialog"),
            "tap_action": call.data.get("tap_action"),
            "position": call.data.get("position", "center"),
        }
        await conn.send_command({"notification": notification})

    hass.services.async_register(
        DOMAIN, SERVICE_SET_PHOTOS, handle_set_photos,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("urls"): vol.All(cv.ensure_list, [cv.string]),
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_NOTIFICATION, handle_send_notification,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Optional("title", default=""): cv.string,
            vol.Optional("message", default=""): cv.string,
            vol.Optional("image_url"): cv.string,
            vol.Optional("duration", default=10): vol.Coerce(int),
            vol.Optional("buttons", default=[]): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("style", default="dialog"): vol.In(["dialog", "toast", "banner"]),
            vol.Optional("tap_action"): cv.string,
            vol.Optional("position", default="center"): vol.In(["center", "top_left", "top_center", "top_right", "bottom_left", "bottom_center", "bottom_right"]),
        }),
    )

    async def handle_open_camera(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        conn = get_connection(hass, device_id)
        if not conn:
            return
        entity_id = call.data["camera_entity"]
        state = hass.states.get(entity_id)
        name = state.attributes.get("friendly_name", entity_id) if state else entity_id
        await conn.send_command({"open_camera": {"id": entity_id, "name": name}})

    hass.services.async_register(
        DOMAIN, SERVICE_OPEN_CAMERA, handle_open_camera,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("camera_entity"): cv.entity_id,
        }),
    )


def _parse_photo_urls(raw: str) -> list[str]:
    """Split comma- or newline-separated URL string into a clean list."""
    import re
    return [u.strip() for u in re.split(r'[,\n]+', raw) if u.strip()]


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    device_id = entry.data[CONF_DEVICE_ID]
    conn = hass.data[DOMAIN].get(device_id, {}).get("connection")
    if conn:
        await conn.stop()

    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(device_id, None)
    return ok


class DeviceConnection:
    """Persistent WebSocket connection from HA to the display device."""

    def __init__(self, hass, entry, device_id, host, port, weather_entity, camera_entities, climate_entity=None, temperature_sensor=None, humidity_sensor=None, auto_ambient_lux=None, ma_media_player=None, door_entities=None, motion_entities=None):
        self._hass = hass
        self._entry = entry
        self._device_id = device_id
        self._host = host
        self._port = port
        self._weather_entity = weather_entity
        self._camera_entities = camera_entities or []
        self._climate_entity = climate_entity
        self._temperature_sensor = temperature_sensor
        self._humidity_sensor = humidity_sensor
        self._auto_ambient_lux = auto_ambient_lux
        self._ma_media_player = ma_media_player
        self._door_entities = door_entities or []
        self._motion_entities = motion_entities or []
        self._auto_ambient_active: bool | None = None
        self._ws = None
        self._running = True
        self._reconnect_delay = 5
        self._unsub_weather = None
        self._unsub_climate = None
        self._unsub_ma = None
        self._unsub_doors = None
        self._unsub_motion = None
        self._camera_task = None
        self._focused_camera: str | None = None
        self._fast_camera_task = None

    async def run(self):
        while self._running:
            try:
                uri = f"ws://{self._host}:{self._port}"
                _LOGGER.info("ha_smart_display: connecting to %s", uri)
                async with websockets.connect(uri, open_timeout=10) as ws:
                    self._ws = ws
                    self._reconnect_delay = 5
                    _LOGGER.info("ha_smart_display: connected to %s", self._device_id)

                    # Subscribe to weather changes
                    if self._weather_entity:
                        self._unsub_weather = async_track_state_change_event(
                            self._hass,
                            [self._weather_entity],
                            self._on_weather_change,
                        )
                        # Push current weather immediately
                        await self._push_weather()

                    # Subscribe to climate / sensor changes
                    climate_sensor_entities = []
                    if self._climate_entity:
                        climate_sensor_entities.append(self._climate_entity)
                    if self._temperature_sensor:
                        climate_sensor_entities.append(self._temperature_sensor)
                    if self._humidity_sensor:
                        climate_sensor_entities.append(self._humidity_sensor)
                    if climate_sensor_entities:
                        self._unsub_climate = async_track_state_change_event(
                            self._hass,
                            climate_sensor_entities,
                            self._on_climate_change,
                        )
                        await self._push_climate()

                    # Subscribe to MA media player state changes
                    if self._ma_media_player:
                        self._unsub_ma = async_track_state_change_event(
                            self._hass,
                            [self._ma_media_player],
                            self._on_ma_state_change,
                        )
                        await self._push_ma_track()

                    # Subscribe to door sensor changes
                    if self._door_entities:
                        self._unsub_doors = async_track_state_change_event(
                            self._hass,
                            self._door_entities,
                            self._on_door_change,
                        )
                        await self._push_doors()

                    # Subscribe to motion sensor changes
                    if self._motion_entities:
                        self._unsub_motion = async_track_state_change_event(
                            self._hass,
                            self._motion_entities,
                            self._on_motion_change,
                        )
                        await self._push_motion()

                    # Push photos and timers/alarms
                    await self._push_photos()
                    await self._push_timers_alarms()

                    # Start camera snapshot loop
                    if self._camera_entities:
                        self._camera_task = self._hass.async_create_task(
                            self._camera_loop()
                        )

                    await self._listen(ws)
            except (OSError, websockets.WebSocketException) as e:
                _LOGGER.warning(
                    "ha_smart_display: connection lost (%s), retrying in %ds",
                    e, self._reconnect_delay,
                )
            finally:
                self._ws = None
                self._set_available(False)
                self._auto_ambient_active = None
                if self._unsub_weather:
                    self._unsub_weather()
                    self._unsub_weather = None
                if self._unsub_climate:
                    self._unsub_climate()
                    self._unsub_climate = None
                if self._unsub_ma:
                    self._unsub_ma()
                    self._unsub_ma = None
                if self._unsub_doors:
                    self._unsub_doors()
                    self._unsub_doors = None
                if self._unsub_motion:
                    self._unsub_motion()
                    self._unsub_motion = None
                if self._camera_task:
                    self._camera_task.cancel()
                    self._camera_task = None
                if self._fast_camera_task:
                    self._fast_camera_task.cancel()
                    self._fast_camera_task = None
                self._focused_camera = None

            if self._running:
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    async def _listen(self, ws):
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "state":
                payload = msg.get("state", {})
                self._hass.data[DOMAIN][self._device_id]["state"] = payload
                self._set_available(True)
                async_dispatcher_send(
                    self._hass,
                    SIGNAL_STATE_UPDATED.format(device_id=self._device_id),
                    payload,
                )
                # Handle dismissed timers/alarms reported by device
                if "dismissed_timer" in payload:
                    self._hass.data[DOMAIN][self._device_id]["timers"].pop(
                        payload["dismissed_timer"], None
                    )
                if "dismissed_alarm" in payload:
                    self._hass.data[DOMAIN][self._device_id]["alarms"].pop(
                        payload["dismissed_alarm"], None
                    )
                # Auto-ambient: switch ambient on/off based on lux threshold
                if self._auto_ambient_lux is not None and "lux" in payload:
                    lux = payload["lux"]
                    if lux is not None:
                        should_be_ambient = lux < self._auto_ambient_lux
                        if should_be_ambient != self._auto_ambient_active:
                            self._auto_ambient_active = should_be_ambient
                            await self.send_command({"ambient_active": should_be_ambient})

                # Handle focused camera — start/stop fast snapshot loop
                if "focused_camera" in payload:
                    focused = payload.get("focused_camera")
                    if focused != self._focused_camera:
                        self._focused_camera = focused
                        if self._fast_camera_task:
                            self._fast_camera_task.cancel()
                            self._fast_camera_task = None
                        if focused and focused in self._camera_entities:
                            self._fast_camera_task = self._hass.async_create_task(
                                self._focused_camera_loop(focused)
                            )

            elif msg_type == "ping":
                await ws.send(json.dumps({"type": "pong"}))

            elif msg_type == "event":
                if msg.get("event") == "voice_command_audio":
                    audio_b64 = msg.get("audio")
                    if audio_b64:
                        import base64 as _b64
                        audio_bytes = _b64.b64decode(audio_b64)
                        self._hass.async_create_task(
                            self._run_voice_pipeline(audio_bytes)
                        )
                elif msg.get("event") == "notification_action":
                    self._hass.bus.async_fire(
                        f"{DOMAIN}_notification_action",
                        {
                            "device_id": self._device_id,
                            "button": msg.get("button"),
                            "index": msg.get("index"),
                        },
                    )
                elif msg.get("event") == "media_command":
                    command = msg.get("command")
                    self._hass.bus.async_fire(
                        f"{DOMAIN}_media_command",
                        {
                            "device_id": self._device_id,
                            "command": command,
                        },
                    )
                    # Forward next/previous to the configured MA media player
                    if self._ma_media_player and command in ("next", "previous"):
                        service = "media_next_track" if command == "next" else "media_previous_track"
                        self._hass.async_create_task(
                            self._hass.services.async_call(
                                "media_player", service,
                                {"entity_id": self._ma_media_player},
                            )
                        )
                    elif self._ma_media_player and command == "shuffle":
                        self._hass.async_create_task(self._handle_shuffle_toggle())
                elif msg.get("event") == "browse_media":
                    category = msg.get("category", "")
                    self._hass.async_create_task(self._handle_browse_request(category))
                elif msg.get("event") == "play_media_item":
                    media_content_id = msg.get("media_content_id", "")
                    media_content_type = msg.get("media_content_type", "")
                    if self._ma_media_player and media_content_id:
                        self._hass.async_create_task(
                            self._hass.services.async_call(
                                "media_player",
                                "play_media",
                                {
                                    "entity_id": self._ma_media_player,
                                    "media_content_id": media_content_id,
                                    "media_content_type": media_content_type,
                                },
                            )
                        )
                elif msg.get("event") == "climate_set_temperature" and self._climate_entity:
                    temperature = msg.get("temperature")
                    if temperature is not None:
                        climate_state = self._hass.states.get(self._climate_entity)
                        if climate_state and climate_state.state == "heat_cool":
                            # heat_cool mode requires target_temp_high + target_temp_low
                            attrs = climate_state.attributes
                            current_high = attrs.get("target_temp_high")
                            current_low = attrs.get("target_temp_low")
                            if current_high is not None and current_low is not None:
                                half_spread = (current_high - current_low) / 2
                                service_data = {
                                    "entity_id": self._climate_entity,
                                    "target_temp_high": temperature + half_spread,
                                    "target_temp_low": temperature - half_spread,
                                }
                            else:
                                service_data = {
                                    "entity_id": self._climate_entity,
                                    "target_temp_high": temperature + 1,
                                    "target_temp_low": temperature - 1,
                                }
                        else:
                            service_data = {
                                "entity_id": self._climate_entity,
                                "temperature": temperature,
                            }
                        await self._hass.services.async_call(
                            "climate", "set_temperature", service_data,
                        )
                elif msg.get("event") == "climate_set_hvac_mode" and self._climate_entity:
                    hvac_mode = msg.get("hvac_mode")
                    if hvac_mode is not None:
                        await self._hass.services.async_call(
                            "climate", "set_hvac_mode",
                            {"entity_id": self._climate_entity, "hvac_mode": hvac_mode},
                        )

    @callback
    def _on_weather_change(self, event) -> None:
        """Called when weather entity state changes."""
        self._hass.async_create_task(self._push_weather())

    @callback
    def _on_climate_change(self, event) -> None:
        """Called when climate entity state changes."""
        self._hass.async_create_task(self._push_climate())

    @callback
    def _on_ma_state_change(self, event) -> None:
        """Called when the MA media player entity state changes."""
        self._hass.async_create_task(self._push_ma_track())

    @callback
    def _on_door_change(self, event) -> None:
        """Called when a door sensor state changes."""
        self._hass.async_create_task(self._push_doors())

    async def _push_doors(self):
        if not self._ws:
            return
        doors = []
        for entity_id in self._door_entities:
            state = self._hass.states.get(entity_id)
            if state is None:
                continue
            name = state.attributes.get("friendly_name", entity_id)
            doors.append({"id": entity_id, "name": name, "open": state.state == "on"})
        await self.send_command({"doors": doors})

    @callback
    def _on_motion_change(self, event) -> None:
        """Called when a motion sensor state changes."""
        self._hass.async_create_task(self._push_motion())

    async def _push_motion(self):
        if not self._ws:
            return
        motions = []
        for entity_id in self._motion_entities:
            state = self._hass.states.get(entity_id)
            if state is None:
                continue
            name = state.attributes.get("friendly_name", entity_id)
            motions.append({"id": entity_id, "name": name, "detected": state.state == "on"})
        await self.send_command({"motions": motions})

    async def _handle_shuffle_toggle(self) -> None:
        """Toggle shuffle on the configured MA media player."""
        if not self._ws or not self._ma_media_player:
            return
        state = self._hass.states.get(self._ma_media_player)
        current = bool(state.attributes.get("shuffle", False)) if state else False
        new_shuffle = not current
        try:
            await self._hass.services.async_call(
                "media_player",
                "shuffle_set",
                {"entity_id": self._ma_media_player, "shuffle": new_shuffle},
            )
            await self.send_command({"shuffle_enabled": new_shuffle})
        except Exception as e:
            _LOGGER.warning("ha_smart_display: shuffle_set failed: %s", e)

    async def _handle_browse_request(self, category: str) -> None:
        """Browse MA media library for a category and push results to device."""
        if not self._ws or not self._ma_media_player:
            return
        # Titles MA uses for each root-level category (matched case-insensitively)
        category_keywords = {
            "artists": ["artist"],
            "albums": ["album"],
            "tracks": ["track", "song"],
            "playlists": ["playlist"],
            "radio": ["radio"],
        }
        keywords = category_keywords.get(category, [category])
        try:
            from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
            entity_comp = self._hass.data.get(MP_DOMAIN)
            if not entity_comp:
                _LOGGER.warning("ha_smart_display: media_player component not found for browse")
                await self.send_command({"browse_result": {"category": category, "items": []}})
                return
            entity = entity_comp.get_entity(self._ma_media_player)
            if not entity or not hasattr(entity, "async_browse_media"):
                _LOGGER.warning("ha_smart_display: MA entity not found or doesn't support browse")
                await self.send_command({"browse_result": {"category": category, "items": []}})
                return

            # Browse root to discover the real content IDs MA uses for each category
            root = await entity.async_browse_media(None, None)
            category_item = None
            for child in (root.children or []):
                title_lower = (child.title or "").lower()
                if any(kw in title_lower for kw in keywords):
                    category_item = child
                    break

            if not category_item:
                _LOGGER.warning(
                    "ha_smart_display: category '%s' not found in MA root browse (children: %s)",
                    category,
                    [c.title for c in (root.children or [])],
                )
                await self.send_command({"browse_result": {"category": category, "items": []}})
                return

            # Browse into the matched category to get actual items
            result = await entity.async_browse_media(
                category_item.media_content_type,
                category_item.media_content_id,
            )
            items = []
            for child in (result.children or []):
                thumbnail = child.thumbnail
                if thumbnail and thumbnail.startswith("/"):
                    try:
                        from homeassistant.helpers.network import get_url
                        base = get_url(self._hass, allow_internal=True, prefer_external=False)
                        thumbnail = f"{base.rstrip('/')}{thumbnail}"
                    except Exception:
                        pass
                subtitle = getattr(child, "media_artist", None) or getattr(child, "media_album_name", None)
                items.append({
                    "title": child.title or "",
                    "subtitle": subtitle,
                    "thumbnail": thumbnail,
                    "media_content_id": child.media_content_id or "",
                    "media_content_type": child.media_content_type or "",
                    "can_play": child.can_play,
                    "can_expand": child.can_expand,
                })
            await self.send_command({"browse_result": {"category": category, "items": items}})
        except Exception as e:
            _LOGGER.warning("ha_smart_display: browse_media failed for '%s': %s", category, e)
            await self.send_command({"browse_result": {"category": category, "items": []}})

    async def _push_ma_track(self):
        if not self._ws or not self._ma_media_player:
            return
        state = self._hass.states.get(self._ma_media_player)
        if not state or state.state in ("unavailable", "unknown", "idle", "off"):
            return
        art_url = state.attributes.get("entity_picture")
        # Resolve relative art URL to absolute so the device can fetch it
        if art_url and art_url.startswith("/"):
            try:
                from homeassistant.helpers.network import get_url
                base = get_url(self._hass, allow_internal=True, prefer_external=False)
                art_url = f"{base.rstrip('/')}{art_url}"
            except Exception:
                pass
        duration = state.attributes.get("media_duration") or 0
        position = state.attributes.get("media_position") or 0
        track = {
            "title": state.attributes.get("media_title") or "",
            "artist": state.attributes.get("media_artist"),
            "album": state.attributes.get("media_album_name"),
            "art_url": art_url,
            "duration_ms": int(duration * 1000),
            "position_ms": int(position * 1000),
        }
        shuffle = bool(state.attributes.get("shuffle", False))
        await self.send_command({"media_track": track, "shuffle_enabled": shuffle})

    async def _push_climate(self):
        if not self._ws:
            return
        has_climate = bool(self._climate_entity)
        has_sensors = bool(self._temperature_sensor or self._humidity_sensor)
        if not has_climate and not has_sensors:
            return

        unit = self._hass.config.units.temperature_unit

        if has_climate:
            state = self._hass.states.get(self._climate_entity)
            if not state:
                return
            attrs = state.attributes
            unit = attrs.get("temperature_unit") or unit
            target_temp = attrs.get("temperature")
            if state.state == "heat_cool":
                high = attrs.get("target_temp_high")
                low = attrs.get("target_temp_low")
                if high is not None and low is not None:
                    target_temp = (high + low) / 2
            current_temp = attrs.get("current_temperature")
            humidity = attrs.get("current_humidity")
            name = attrs.get("friendly_name", self._climate_entity)
            hvac_mode = state.state
            hvac_modes = attrs.get("hvac_modes", [])
            min_temp = attrs.get("min_temp", 7)
            max_temp = attrs.get("max_temp", 35)
        else:
            # Sensor-only — read-only, no climate control
            current_temp = None
            humidity = None
            name = None
            hvac_mode = "off"
            hvac_modes = []
            target_temp = None
            min_temp = 7
            max_temp = 35

        # Sensor values override climate entity's built-in readings if configured
        if self._temperature_sensor:
            temp_state = self._hass.states.get(self._temperature_sensor)
            if temp_state and temp_state.state not in ("unknown", "unavailable"):
                try:
                    current_temp = float(temp_state.state)
                    unit = temp_state.attributes.get("unit_of_measurement") or unit
                    if name is None:
                        name = temp_state.attributes.get("friendly_name", self._temperature_sensor)
                except ValueError:
                    pass

        if self._humidity_sensor:
            hum_state = self._hass.states.get(self._humidity_sensor)
            if hum_state and hum_state.state not in ("unknown", "unavailable"):
                try:
                    humidity = int(float(hum_state.state))
                    if name is None:
                        name = hum_state.attributes.get("friendly_name", self._humidity_sensor)
                except ValueError:
                    pass

        if name is None:
            name = "Room Sensor"

        climate_payload = {
            "name": name,
            "current_temperature": current_temp,
            "humidity": humidity,
            "target_temperature": target_temp,
            "hvac_mode": hvac_mode,
            "hvac_modes": hvac_modes,
            "min_temp": min_temp,
            "max_temp": max_temp,
            "unit": unit,
        }
        await self.send_command({"climate": climate_payload})

    async def _push_weather(self):
        if not self._weather_entity or not self._ws:
            return
        state = self._hass.states.get(self._weather_entity)
        if not state:
            return
        attrs = state.attributes
        unit = self._hass.config.units.temperature_unit

        # Fetch hourly forecast via modern HA service call
        forecast = []
        for forecast_type in ("hourly", "daily"):
            try:
                response = await self._hass.services.async_call(
                    "weather",
                    "get_forecasts",
                    {"entity_id": self._weather_entity, "type": forecast_type},
                    blocking=True,
                    return_response=True,
                )
                periods = response.get(self._weather_entity, {}).get("forecast", [])
                if periods:
                    forecast = periods[:24]
                    break
            except Exception as e:
                _LOGGER.debug("ha_smart_display: forecast type %s failed: %s", forecast_type, e)

        weather_payload = {
            "condition": state.state,
            "temperature": attrs.get("temperature"),
            "temperature_unit": unit,
            "humidity": attrs.get("humidity"),
            "wind_speed": attrs.get("wind_speed"),
            "forecast": forecast,
        }
        await self.send_command({"weather": weather_payload})

    async def _push_photos(self):
        photos = self._hass.data[DOMAIN].get(self._device_id, {}).get("photos", [])
        await self.send_command({"photos": photos})

    async def _camera_loop(self):
        """Push camera snapshots while connected — 10s when visible, 60s otherwise."""
        while self._ws is not None:
            await self._push_camera_snapshots()
            device_state = self._hass.data[DOMAIN].get(self._device_id, {}).get("state", {})
            cameras_visible = (
                device_state.get("ambient_mode") == "cameras"
                and not device_state.get("ambient_active", False)
            )
            await asyncio.sleep(10 if cameras_visible else 60)

    async def _push_camera_snapshots(self):
        from homeassistant.components.camera import async_get_image
        cameras = []
        for entity_id in self._camera_entities:
            try:
                image = await async_get_image(self._hass, entity_id, timeout=5)
                b64 = base64.b64encode(image.content).decode()
                state = self._hass.states.get(entity_id)
                name = (state.attributes.get("friendly_name", entity_id) if state else entity_id)
                cameras.append({"id": entity_id, "name": name, "data": b64})
            except Exception as e:
                _LOGGER.debug("ha_smart_display: camera snapshot failed for %s: %s", entity_id, e)
        if cameras:
            await self.send_command({"cameras": cameras})

    async def _focused_camera_loop(self, entity_id: str):
        """Push snapshots for a focused camera at ~1fps."""
        from homeassistant.components.camera import async_get_image
        while self._ws is not None and self._focused_camera == entity_id:
            try:
                image = await async_get_image(self._hass, entity_id, timeout=5)
                b64 = base64.b64encode(image.content).decode()
                state = self._hass.states.get(entity_id)
                name = state.attributes.get("friendly_name", entity_id) if state else entity_id
                await self.send_command({"focused_camera_data": {"id": entity_id, "name": name, "data": b64}})
            except Exception as e:
                _LOGGER.debug("ha_smart_display: focused camera snapshot failed: %s", e)
            await asyncio.sleep(1)

    async def _push_timers_alarms(self):
        data = self._hass.data[DOMAIN].get(self._device_id, {})
        now = int(datetime.now().timestamp())
        # Add remaining_seconds so Flutter can compute ends_at locally,
        # avoiding clock drift and correctly handling reconnect.
        timers = [
            {**t, "remaining_seconds": max(0, t["ends_at"] - now)}
            for t in data.get("timers", {}).values()
        ]
        alarms = list(data.get("alarms", {}).values())
        await self.send_command({"timers": timers, "alarms": alarms})

    async def _run_voice_pipeline(self, audio_bytes: bytes) -> None:
        """Run HA Assist pipeline on device-recorded audio and send back the response."""
        try:
            from homeassistant.components.assist_pipeline import (
                async_pipeline_from_audio_stream,
                PipelineEvent,
                PipelineEventType,
                PipelineStage,
            )
            from homeassistant.components.stt import (
                SpeechMetadata,
                AudioBitRates,
                AudioChannels,
                AudioCodecs,
                AudioFormats,
                AudioSampleRates,
            )
            from homeassistant.core import Context
        except ImportError as e:
            _LOGGER.warning("ha_smart_display: assist_pipeline not available: %s", e)
            return

        result: dict = {}

        def event_callback(event: PipelineEvent) -> None:
            if event.type == PipelineEventType.STT_END:
                stt_text = event.data.get("stt_output", {}).get("text", "") if event.data else ""
                _LOGGER.debug("ha_smart_display: STT result: %r", stt_text)
            elif event.type == PipelineEventType.INTENT_END:
                # Primary source for response text — always fires even when TTS doesn't
                try:
                    result["text"] = (
                        event.data["intent_output"]["response"]["speech"]["plain"]["speech"]
                        if event.data else ""
                    )
                except (KeyError, TypeError):
                    pass
            elif event.type == PipelineEventType.TTS_END:
                result["tts_url"] = (
                    event.data.get("tts_output", {}).get("url") if event.data else None
                )
            elif event.type == PipelineEventType.ERROR:
                msg = event.data.get("message", "Unknown error") if event.data else "error"
                _LOGGER.warning("ha_smart_display: voice pipeline error: %s", msg)

        async def audio_stream():
            chunk_size = 8000  # ~250 ms at 16 kHz 16-bit
            for i in range(0, len(audio_bytes), chunk_size):
                yield audio_bytes[i : i + chunk_size]

        try:
            await async_pipeline_from_audio_stream(
                self._hass,
                context=Context(),
                event_callback=event_callback,
                stt_metadata=SpeechMetadata(
                    language=self._hass.config.language,
                    format=AudioFormats.WAV,
                    codec=AudioCodecs.PCM,
                    bit_rate=AudioBitRates.BITRATE_16,
                    sample_rate=AudioSampleRates.SAMPLERATE_16000,
                    channel=AudioChannels.CHANNEL_MONO,
                ),
                stt_stream=audio_stream(),
                pipeline_id=None,
                start_stage=PipelineStage.STT,
                end_stage=PipelineStage.TTS,
            )
        except Exception as e:
            _LOGGER.warning("ha_smart_display: voice pipeline failed: %s", e)
            return

        response_text = result.get("text", "")
        _LOGGER.debug("ha_smart_display: voice pipeline result: %r", response_text)

        # Resolve relative tts_url to a full URL the device can fetch directly
        tts_url = result.get("tts_url")
        if tts_url:
            try:
                from homeassistant.helpers.network import get_url
                base_url = get_url(self._hass, allow_internal=True, prefer_external=False)
                tts_url = f"{base_url.rstrip('/')}{tts_url}"
            except Exception as e:
                _LOGGER.warning("ha_smart_display: could not resolve TTS URL: %s", e)
                tts_url = None

        await self.send_command({
            "voice_response": {
                "text": response_text,
                "tts_url": tts_url,
            }
        })

    def _set_available(self, available: bool):
        data = self._hass.data.get(DOMAIN, {}).get(self._device_id)
        if data and data.get("available") != available:
            data["available"] = available
            async_dispatcher_send(
                self._hass,
                SIGNAL_AVAILABILITY_UPDATED.format(device_id=self._device_id),
                available,
            )

    async def send_command(self, payload: dict):
        if self._ws is None:
            _LOGGER.warning(
                "ha_smart_display: cannot send command, not connected (%s)",
                self._device_id,
            )
            return
        try:
            await self._ws.send(json.dumps({"type": "command", "payload": payload}))
        except Exception as e:
            _LOGGER.warning("ha_smart_display: send failed: %s", e)

    async def stop(self):
        self._running = False
        if self._fast_camera_task:
            self._fast_camera_task.cancel()
            self._fast_camera_task = None
        if self._ws:
            await self._ws.close()


def get_connection(hass: HomeAssistant, device_id: str) -> "DeviceConnection | None":
    return hass.data.get(DOMAIN, {}).get(device_id, {}).get("connection")


def resolve_device_id(hass: HomeAssistant, ha_device_id: str) -> str | None:
    """Convert an HA device registry ID to our internal device_id."""
    from homeassistant.helpers import device_registry as dr
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(ha_device_id)
    if not device:
        return None
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN:
            return entry.data.get(CONF_DEVICE_ID)
    return None
