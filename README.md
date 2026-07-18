# HA Smart Display

A Home Assistant custom integration that turns an Amazon Echo Show 8 (running a custom Flutter app) into a fully-featured smart home display. The integration communicates with the device over a local WebSocket connection and pushes real-time updates for weather, cameras, timers, alarms, climate, and music.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

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

## Companion app

The device-side Flutter app is available at [ha-smart-display-app](https://github.com/alec-pinson/ha-smart-display-app).
