# ha-smart-display-integration

Home Assistant custom integration. See root `CLAUDE.md` for full architecture.

## Installation / deployment (test pod)
```bash
POD=$(kubectl --context pi-k8s-cluster get pods -n default --no-headers | grep test-home-assistant | awk '{print $1}')
kubectl --context pi-k8s-cluster exec -n default $POD -- rm -rf /config/custom_components/ha_smart_display
kubectl --context pi-k8s-cluster cp ~/git/personal/ha-smart-display/ha-smart-display-integration/custom_components/ha_smart_display default/$POD:/config/custom_components/ha_smart_display
kubectl --context pi-k8s-cluster delete pod -n default $POD
```
Always use `--context pi-k8s-cluster`. Always delete the pod after copying.

## Quick reference — adding a new entity
1. Create or update the relevant platform file (`switch.py`, `select.py`, etc.)
2. Add new state key to `SIGNAL_STATE_UPDATED` handler in `entity_base.py` if needed
3. Add `send_command()` call with the right payload key
4. Handle the key in Flutter's `DisplayStateNotifier.applyCommand()`
5. Add string to `strings.json` if new config/options field

## DeviceConnection lifecycle
```
async_setup_entry()
  → DeviceConnection.run()  [background task, reconnects forever]
    → websockets.connect(ws://host:8472)
    → on connect: send immich_config (if Immich configured) + schedule immich refresh timer
                  send slideshow_interval command
                  push weather + photos (static + Immich merged) + timers/alarms + climate
                  start camera loop
                  subscribe to MA media player entity if configured + push current track
                  subscribe to door/motion entities if configured + push initial state
    → _listen(): handles "state" messages → dispatcher_send → entities update
                 detects focused_camera changes → starts/stops _focused_camera_loop
                 handles "event" messages → notification_action HA event,
                   climate_set_temperature/hvac_mode → climate service calls,
                   media_command → ha_smart_display_media_command HA event + forward next/previous to MA entity
    → on disconnect: set unavailable, unsubscribe weather/MA/doors/motion/immich_refresh, cancel tasks, retry with backoff
```

## Camera loops
- **`_camera_loop`**: runs while connected; pushes all configured camera snapshots as `{"cameras": [...]}`. Sleep 10s when cameras mode visible, 60s otherwise.
- **`_focused_camera_loop(entity_id)`**: started when device reports `focused_camera` in state. Pushes single camera as `{"focused_camera_data": {...}}` at ~1fps. Cancelled when `focused_camera` becomes null or connection drops.

## Adding a new service
1. Define in `const.py` (`SERVICE_*`)
2. Implement handler + register in `_register_services()` in `__init__.py`
3. Add schema validation using `resolve_device_id()` to map HA device registry ID → internal device_id
4. Add field definitions to `services.yaml` (use `device: {integration: ha_smart_display}` selector for device_id; use `select` selector for enum fields)
5. Call `conn.send_command({...})` with appropriate payload

## resolve_device_id()
All service handlers call `resolve_device_id(hass, call.data["device_id"])` which looks up
the HA device registry entry and returns the integration's internal `device_id` string.
The `device_id` field in services.yaml uses `selector: device: {integration: ha_smart_display}`
so users get a drop-down picker rather than having to type a raw ID.

## Timer accuracy
HA computes `remaining_seconds = max(0, int(ends_at - time.time()))` at send time and includes
it alongside `ends_at` in the timers payload. Flutter uses `remaining_seconds` if present,
avoiding clock drift on reconnect.

`_push_timers_alarms()` always sends `{"timers": [...], "alarms": [...]}` on connect, even when
both lists are empty — this clears any stale data the device had from the previous session.

## Weather push
- Triggered on connect + on `async_track_state_change_event` for the configured weather entity
- Uses `weather.get_forecasts` service (hourly, falls back to daily), sends up to 24 periods
- Sends `{"weather": {"condition", "temperature", "temperature_unit", "humidity", "wind_speed", "forecast"}}`

## send_notification fields
`style`: dialog / toast / banner. `position` (dialog only): center / top_left / top_center / top_right / bottom_left / bottom_center / bottom_right — maps to `Dialog.alignment` on the Flutter side. Both validated via `vol.In` in the schema.

## Notification events
When the device fires a notification action (button press or tap_action), it sends:
`{"type": "event", "event": "notification_action", "button": "...", "index": N}`
`_listen()` handles this and fires the `ha_smart_display_notification_action` HA event with
`device_id`, `button`, and `index` as event data. Tap actions use index -1.

## Climate push
- Triggered on connect + `async_track_state_change_event` for climate/sensor entities (stored in `_unsub_climate`)
- Handles three modes: climate entity only, sensors only, or both (sensors override entity readings)
- Sensor-only mode sends `hvac_modes: []` — Flutter treats this as read-only (shows thermometer icon, hides controls)
- `heat_cool` mode: preserves spread when setting target temp — `target_temp_high = temp + half_spread`, `target_temp_low = temp - half_spread`

## Options flow pattern for optional entity fields
Use `add_suggested_values_to_schema` — do NOT use `vol.Optional(field, default=value)`. Voluptuous substitutes the default when a user clears a field, preventing deletion. Strip empty/None on submit:
```python
data = {k: v for k, v in user_input.items() if v not in (None, "")}
return self.async_create_entry(title="", data=data)
```

## Media player entity (`media_player.py`)
- `HaSmartDisplayMediaPlayer` — supports PLAY_MEDIA, PAUSE, PLAY, STOP, SEEK, NEXT/PREVIOUS, VOLUME_SET, MEDIA_ANNOUNCE
- `async_play_media` resolves URLs in order: `media-source://` URIs → `media_source.async_resolve_media`; relative `/api/...` paths → prepend `get_url(hass, allow_internal=True)`
- Works with `tts.speak` (modern HA passes `media-source://tts/...`) and Music Assistant
- MA streams from its own HTTP server on port **8097** — device firewall must allow access to that port
- **MA metadata structure**: MA nests metadata under `extra["metadata"]` with camelCase keys: `title`, `artist`, `album`/`albumName`, `imageUrl`, `images[].url`, `duration`. Top-level `extra` keys also tried as fallback for other callers.
- **MA media player option** (`ma_media_player` in options): when configured, `DeviceConnection` subscribes to that entity's state changes and pushes `{"media_track": {...}}` to the device whenever the track changes. This provides real per-track metadata (title/artist/art) for MA flow streams. Relative `entity_picture` URLs are resolved to absolute.
- When `ma_media_player` is configured: `async_play_media` sends empty title/art (MA entity provides it via `media_track`), then immediately calls `_push_ma_track()` — both arrive in the same burst so there's no "Music Assistant" flash between tracks.
- When device taps next/previous: fires `ha_smart_display_media_command` HA event + calls `media_player.media_next/previous_track` on the configured MA entity
- When device sends `shuffle` media_command: `_handle_shuffle_toggle()` reads current shuffle state from MA entity state, calls `media_player.shuffle_set` with toggled value
- `media_state` "buffering" maps to `MediaPlayerState.PLAYING` in HA (so HA/MA see it as playing during buffer)

## Music library browsing
Device can browse the MA media library via a two-step protocol:

1. **Device sends** `{"type": "event", "event": "browse_media", "category": "artists"}` (categories: artists / albums / tracks / playlists / radio)
2. **Integration** calls `_handle_browse_request(category)`:
   - Gets MA entity via `hass.data["media_player"].get_entity(ma_entity_id)`
   - Browses root first (`async_browse_media(None, None)`) to discover the real content IDs MA uses
   - Matches root child by title keyword (e.g. "artist" in child.title.lower())
   - Browses into that child to get actual items
   - Resolves relative thumbnail URLs to absolute
   - Sends `{"browse_result": {"category": "...", "items": [...]}}` back to device
3. **Device sends** `{"type": "event", "event": "play_media_item", "media_content_id": "...", "media_content_type": "..."}` to play a browsed item
4. **Integration** calls `media_player.play_media` service on MA entity

**Key**: always browse root first — do NOT guess at MA content IDs. MA's content ID format varies across versions; discovering from root ensures correct IDs.

## Immich integration
- **`ImmichProvider`** class in `__init__.py` — instantiated per `DeviceConnection` if `immich_url + immich_api_key + immich_album_ids` all present in options
- `fetch_photos()` calls `GET /api/albums/{id}` for each album, collects image asset IDs, shuffles, takes `batch_size`, returns thumbnail URLs (`/api/assets/{id}/thumbnail?size=preview`)
- `_push_photos()` merges static `photo_urls` + Immich results, shuffles, sends `{"photos": [...]}` — always sends even when Immich returns empty
- `_send_immich_config()` sends `{"immich_config": {"url": ..., "api_key": ...}}` once per connection so Flutter can add auth headers
- Periodic refresh: `async_track_time_interval` schedules `_on_immich_refresh` every N minutes; unsubscribed in `finally` block on disconnect
- **Options flow is two-step**: `async_step_init` validates credentials + fetches albums; on success stores pending options + album list and calls `async_step_immich_albums`; on failure shows `immich_connection_failed` error; `async_step_immich_albums` shows `SelectSelector(multiple=True)` populated from the fetched album list
- Strip `immich_album_ids` from saved options when Immich URL or API key is cleared
- `slideshow_interval` stored in options as minutes, sent to device as seconds (`× 60`)
- Next/Previous Photo buttons in `button.py` send `{"photo_command": "next/previous"}`

## Important HA version note
`ZeroconfServiceInfo` is at `homeassistant.helpers.service_info.zeroconf` — NOT `homeassistant.components.zeroconf`.
