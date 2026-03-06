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
    → on connect: push weather + photos + timers/alarms + climate, start camera loop
    → _listen(): handles "state" messages → dispatcher_send → entities update
                 detects focused_camera changes → starts/stops _focused_camera_loop
                 handles "event" messages → notification_action HA event, climate_set_temperature/hvac_mode → climate service calls
    → on disconnect: set unavailable, unsubscribe weather, cancel tasks, retry with backoff
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

## Important HA version note
`ZeroconfServiceInfo` is at `homeassistant.helpers.service_info.zeroconf` — NOT `homeassistant.components.zeroconf`.
