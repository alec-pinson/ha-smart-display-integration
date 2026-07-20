# HA Smart Display

A Home Assistant custom integration that turns an Amazon Echo Show 8 (running a custom Flutter app) into a fully-featured smart home display. The integration communicates with the device over a local WebSocket connection and pushes real-time updates for weather, cameras, timers, alarms, climate, and music.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

## Screenshots

_Coming soon._

## Features

- **Weather** — real-time conditions and hourly/daily forecast
- **Cameras** — live snapshots and full-screen RTSP/go2rtc streams with audio
- **Climate** — temperature display and control (thermostat entity or separate sensors)
- **Timers & alarms** — synced from HA timers and alarm control panels
- **Music** — Music Assistant integration with track metadata and playback control
- **Photos** — rotating slideshow from static URLs or an Immich library
- **Voice assistant** — Alexa wake word + HA Assist pipeline via Wyoming
- **Notifications** — push dialog/toast/banner notifications from HA automations
- **Auto-discovery** — device appears in HA via Zeroconf (no manual IP entry needed)

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=alec-pinson&repository=ha-smart-display-integration&category=integration)

1. Click the button above to open HACS and add this repository.
2. Install **HA Smart Display** from HACS.
3. Restart Home Assistant.

### Manual

1. Copy the `custom_components/ha_smart_display` folder into your HA `config/custom_components/` directory.
2. Restart Home Assistant.

## Setup

1. Install and launch the [HA Smart Display app](https://github.com/alec-pinson/ha-smart-display-app) on your Echo Show 8.
2. The device will be auto-discovered in **Settings → Integrations**. Accept the pairing prompt and enter the pairing code shown on the device screen.
3. If auto-discovery doesn't appear, click **+ Add Integration**, search for **HA Smart Display**, and enter the device's IP address manually.

A single display can be paired with several Home Assistant instances and switched
between them from the device's Device Status dialog. Only the active instance is
served; the others will show the display as unavailable, which is expected.

## Configuration

After setup, configure optional features via **Settings → Integrations → HA Smart Display → Configure**:

| Option | Description |
|---|---|
| Weather entity | Entity ID of a `weather.*` entity for forecast data |
| Photo URLs | Newline-separated list of image URLs for the slideshow |
| Camera entities | Camera entity IDs to show on the cameras screen |
| Climate entity | Thermostat entity for temperature display and control |
| Temperature / humidity sensor | Override thermostat readings with separate sensor entities |
| Music Assistant media player | MA entity for track metadata and playback control |
| Immich URL + API key | Immich instance for photo library slideshow |
| Slideshow interval | How often to advance the photo (minutes, default 1) |
| go2rtc URL | go2rtc server URL for live RTSP camera streams with audio |
| Frigate URL | Frigate NVR URL (used for stream source resolution) |
| Beta app updates | Offer pre-release app builds for testing. Off by default. |

### Beta app updates

With this off (the default), the display is offered the latest stable app release.
With it on, it is offered whichever release was published most recently — including
pre-releases.

The channel means "newest release wins", not "pre-releases only": once a stable
release is published on top of a beta, devices on the beta channel follow it and both
channels converge. Note that pre-releases do not expire — if betas are cut for a
version that is then abandoned, a beta device stays on that build until a newer
release appears.

## Entities

Each paired display gets the following entities.

| Entity | Type | Description |
|---|---|---|
| Display Mode | select | Switch between clock, weather, cameras and music |
| Ambient | switch | Dimmed, low-activity night mode |
| Screen | switch | Turn the display on or off |
| Brightness | number | 10–255 |
| Auto Brightness | switch | Follow the ambient light sensor |
| Volume | number | 0–100 |
| Do Not Disturb | switch | Suppress notifications and alerts |
| Alarm | switch | Alarm currently sounding |
| Siren | switch | Trigger the siren sound |
| Media Player | media_player | Music Assistant playback control |
| Assist | assist_satellite | Voice assistant satellite |
| Wake Word | select | Which wake word to listen for |
| Wake Word Sensitivity | select | Detection threshold |
| Wake Word Sound | switch | Play a sound on wake word detection |
| Finished Speaking Detection | select | End-of-speech sensitivity |
| Mute Microphone | switch | Disable the microphone |
| Wake for Voice | button | Start a voice interaction remotely |
| Restart | button | Restart the app |
| Next Photo / Previous Photo | button | Advance the slideshow |
| Check for Updates | button | Poll GitHub for a new app release now |
| Screen | camera | The most recent screenshot captured from the display. Updated only when a capture is triggered; the `last_captured` attribute shows its age. |
| Take Screenshot | button | Capture the display's screen. Fire-and-forget — the image lands on the camera entity a moment later. |
| App | update | Install app updates over the air |
| Uptime | sensor | App uptime |
| Wake Word Count | sensor | Detections since start |
| Illuminance | sensor | Ambient light level |
| Memory Usage | sensor | Disabled by default (diagnostic) |
| Thread Count | sensor | Disabled by default (diagnostic) |

## Services

| Service | Description |
|---|---|
| `ha_smart_display.send_notification` | Push a dialog, toast, or banner to the display |
| `ha_smart_display.show_camera_stream` | Open a full-screen camera view |
| `ha_smart_display.close_camera_stream` | Close the full-screen camera view |
| `ha_smart_display.set_timer` | Set a countdown timer on the device |
| `ha_smart_display.dismiss_timer` | Dismiss a running timer |
| `ha_smart_display.set_alarm` | Set an alarm on the device |
| `ha_smart_display.dismiss_alarm` | Dismiss an alarm |
| `ha_smart_display.set_photos` | Push a new set of photo URLs to the slideshow |
| `ha_smart_display.add_pill` | Add or update a status pill on the display |
| `ha_smart_display.remove_pill` | Remove a pill by id |
| `ha_smart_display.dismiss_all_pills` | Remove all pills from the display |
| `ha_smart_display.take_screenshot` | Capture the display's screen and wait for it to land on the camera entity |

### `ha_smart_display.take_screenshot`

Capture the display's screen and store it on the camera entity. Unlike the
Take Screenshot button, this service **waits** until the image has arrived, so
a following `camera.snapshot` saves the new capture rather than the previous
one.

| Parameter | Required | Description |
|---|---|---|
| `device_id` | yes | The display to capture |

Saving a screenshot to disk:

```yaml
sequence:
  - service: ha_smart_display.take_screenshot
    data:
      device_id: echo_show_kitchen
  - service: camera.snapshot
    target:
      entity_id: camera.echo_show_kitchen_screen
    data:
      filename: /config/www/display.png
```

Screenshots are held in memory only — nothing is written to the device's
storage, and only the most recent capture is kept.

## Pills

Pills are small status chips shown on the clock screen. They are created and removed
entirely from automations, persist across app restarts, and every pill is tappable.

### `add_pill` parameters

| Parameter | Required | Description |
|---|---|---|
| `device_id` | yes | Target display |
| `pill_id` | yes | Your identifier, used to update or remove the pill later |
| `text` | yes | Pill label |
| `icon` | no | See icon list below |
| `color` | no | Hex colour, e.g. `"#C62828"` |
| `size` | no | `small`, `medium` (default), or `large` |
| `position` | no | `under_clock` (default), `top_left`, `top_center`, `top_right`, `center_left`, `center`, `center_right`, `bottom_left`, `bottom_center`, `bottom_right` |
| `duration` | no | Seconds until the pill removes itself |

Calling `add_pill` with an existing `pill_id` updates that pill in place.

### Icons

`door`, `motion`, `warning`, `info`, `check`, `alert`, `camera`, `lock`,
`temperature`, `person`, `trash`

### Sizes

| Size | Padding (H×V) | Icon | Font |
|---|---|---|---|
| `small` | 8×4 | 12 | 11 |
| `medium` | 12×6 | 16 | 14 |
| `large` | 16×8 | 20 | 17 |

## Events

### `ha_smart_display_pill_tap`

Fired when any pill on the display is tapped. Every pill is tappable — there is
no flag to set when creating one.

| Field | Description |
|---|---|
| `device_id` | The display the pill was tapped on |
| `pill_id` | The `pill_id` given to `add_pill` |

The pill stays on screen after a tap. Call `remove_pill` from your automation
if you want it dismissed.

Taps are rate-limited to one every 500ms per pill, so an accidental double-tap
fires the automation once.

Pills are tappable in normal mode only. In ambient mode the first tap wakes the
display; tap the pill again once the display is awake.

Show a pill when the front door is left unlocked:

```yaml
automation:
  - alias: Front door unlocked pill
    trigger:
      platform: state
      entity_id: lock.front_door
      to: unlocked
    action:
      service: ha_smart_display.add_pill
      data:
        device_id: echo_show_kitchen
        pill_id: front_door
        text: "Front door unlocked"
        icon: lock
        color: "#C62828"
```

Lock the door and clear the pill when it's tapped:

```yaml
automation:
  - alias: Front door pill tapped
    trigger:
      platform: event
      event_type: ha_smart_display_pill_tap
      event_data:
        pill_id: front_door
    action:
      - service: lock.lock
        target:
          entity_id: lock.front_door
      - service: ha_smart_display.remove_pill
        data:
          device_id: echo_show_kitchen
          pill_id: front_door
```

## Companion app

The device-side Flutter app is available at [ha-smart-display-app](https://github.com/alec-pinson/ha-smart-display-app).

## Sponsor

If you find this project useful, you can support its development:

- [Ko-fi](https://ko-fi.com/alecpinson)
- [PayPal](https://paypal.me/alecpinson1)

## Licence

MIT — see [LICENSE](LICENSE).
