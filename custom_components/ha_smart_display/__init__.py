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
    SIGNAL_STATE_UPDATED,
    SIGNAL_AVAILABILITY_UPDATED,
    SERVICE_SET_TIMER,
    SERVICE_DISMISS_TIMER,
    SERVICE_SET_ALARM,
    SERVICE_DISMISS_ALARM,
    SERVICE_SET_PHOTOS,
    SERVICE_SEND_NOTIFICATION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["select", "switch", "number", "button", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    device_id = entry.data[CONF_DEVICE_ID]
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    weather_entity = entry.options.get(CONF_WEATHER_ENTITY) or entry.data.get(CONF_WEATHER_ENTITY)
    photo_urls = _parse_photo_urls(entry.options.get(CONF_PHOTO_URLS, ""))
    camera_entities = entry.options.get(CONF_CAMERA_ENTITIES, [])

    hass.data.setdefault(DOMAIN, {})[device_id] = {
        "state": {},
        "available": False,
        "connection": None,
        "timers": {},
        "alarms": {},
        "photos": photo_urls,
    }

    connection = DeviceConnection(hass, entry, device_id, host, port, weather_entity, camera_entities)
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
        device_id = call.data["device_id"]
        conn = get_connection(hass, device_id)
        if not conn:
            return
        timer = {
            "id": call.data["timer_id"],
            "label": call.data.get("label", "Timer"),
            "duration_seconds": call.data["duration_seconds"],
            "ends_at": int(datetime.now().timestamp()) + call.data["duration_seconds"],
        }
        hass.data[DOMAIN][device_id]["timers"][timer["id"]] = timer
        await conn.send_command({"timers": list(hass.data[DOMAIN][device_id]["timers"].values())})

    async def handle_dismiss_timer(call: ServiceCall) -> None:
        device_id = call.data["device_id"]
        timer_id = call.data["timer_id"]
        conn = get_connection(hass, device_id)
        hass.data[DOMAIN][device_id]["timers"].pop(timer_id, None)
        if conn:
            await conn.send_command({"timers": list(hass.data[DOMAIN][device_id]["timers"].values())})

    async def handle_set_alarm(call: ServiceCall) -> None:
        device_id = call.data["device_id"]
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
        device_id = call.data["device_id"]
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
        device_id = call.data["device_id"]
        urls = call.data.get("urls", [])
        conn = get_connection(hass, device_id)
        hass.data[DOMAIN][device_id]["photos"] = urls
        if conn:
            await conn.send_command({"photos": urls})

    async def handle_send_notification(call: ServiceCall) -> None:
        device_id = call.data["device_id"]
        conn = get_connection(hass, device_id)
        if not conn:
            return
        notification = {
            "title": call.data.get("title", ""),
            "message": call.data.get("message", ""),
            "image_url": call.data.get("image_url"),
            "duration": call.data.get("duration", 10),
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

    def __init__(self, hass, entry, device_id, host, port, weather_entity, camera_entities):
        self._hass = hass
        self._entry = entry
        self._device_id = device_id
        self._host = host
        self._port = port
        self._weather_entity = weather_entity
        self._camera_entities = camera_entities or []
        self._ws = None
        self._running = True
        self._reconnect_delay = 5
        self._unsub_weather = None
        self._camera_task = None

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
                if self._unsub_weather:
                    self._unsub_weather()
                    self._unsub_weather = None
                if self._camera_task:
                    self._camera_task.cancel()
                    self._camera_task = None

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

            elif msg_type == "ping":
                await ws.send(json.dumps({"type": "pong"}))

    @callback
    def _on_weather_change(self, event) -> None:
        """Called when weather entity state changes."""
        self._hass.async_create_task(self._push_weather())

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
        if photos:
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

    async def _push_timers_alarms(self):
        data = self._hass.data[DOMAIN].get(self._device_id, {})
        timers = list(data.get("timers", {}).values())
        alarms = list(data.get("alarms", {}).values())
        if timers or alarms:
            await self.send_command({"timers": timers, "alarms": alarms})

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
        if self._ws:
            await self._ws.close()


def get_connection(hass: HomeAssistant, device_id: str) -> "DeviceConnection | None":
    return hass.data.get(DOMAIN, {}).get(device_id, {}).get("connection")
