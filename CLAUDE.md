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
    → on connect: push weather + photos + timers/alarms, start camera loop
    → _listen(): handles "state" messages → dispatcher_send → entities update
                 detects focused_camera changes → starts/stops _focused_camera_loop
    → on disconnect: set unavailable, unsubscribe weather, cancel tasks, retry with backoff
```

## Camera loops
- **`_camera_loop`**: runs while connected; pushes all configured camera snapshots as `{"cameras": [...]}`. Sleep 10s when cameras mode visible, 60s otherwise.
- **`_focused_camera_loop(entity_id)`**: started when device reports `focused_camera` in state. Pushes single camera as `{"focused_camera_data": {...}}` at ~1fps. Cancelled when `focused_camera` becomes null or connection drops.

## Adding a new service
1. Define in `const.py` (`SERVICE_*`)
2. Implement handler + register in `_register_services()` in `__init__.py`
3. Add schema validation
4. Call `conn.send_command({...})` with appropriate payload

## Weather push
- Triggered on connect + on `async_track_state_change_event` for the configured weather entity
- Uses `weather.get_forecasts` service (hourly, falls back to daily), sends up to 24 periods
- Sends `{"weather": {"condition", "temperature", "temperature_unit", "humidity", "wind_speed", "forecast"}}`

## Important HA version note
`ZeroconfServiceInfo` is at `homeassistant.helpers.service_info.zeroconf` — NOT `homeassistant.components.zeroconf`.
