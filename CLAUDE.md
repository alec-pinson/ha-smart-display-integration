# ha-smart-display-integration

Home Assistant custom integration. See root `CLAUDE.md` for full architecture.

## Installation
Copy `custom_components/ha_smart_display/` to `/config/custom_components/ha_smart_display/` on the HA instance.
Restart HA after any Python file change.

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
    → on connect: subscribe to weather state changes, push weather + timers/alarms
    → _listen(): handles "state" messages → dispatcher_send → entities update
    → on disconnect: set unavailable, unsubscribe weather, retry with backoff
```

## Adding a new service
1. Define in `const.py` (`SERVICE_*`)
2. Implement handler + register in `_register_services()` in `__init__.py`
3. Add schema validation
4. Call `conn.send_command({...})` with appropriate payload

## Weather push
- Triggered on connect + on `async_track_state_change_event` for the configured weather entity
- Weather entity configured via options flow (gear icon on integration)
- Sends `{"weather": {"condition", "temperature", "temperature_unit", "humidity", "wind_speed", "forecast"}}`

## Important HA version note
`ZeroconfServiceInfo` is at `homeassistant.helpers.service_info.zeroconf` — NOT `homeassistant.components.zeroconf`.
