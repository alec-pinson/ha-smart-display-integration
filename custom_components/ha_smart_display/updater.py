import logging
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import GITHUB_RELEASE_REPO, UPDATE_CHECK_INTERVAL

_LOGGER = logging.getLogger(__name__)

GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_RELEASE_REPO}/releases/latest"


class GitHubUpdater:
    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self.latest_version: str | None = None
        self.latest_apk_url: str | None = None
        self.release_html_url: str | None = None
        self.last_checked: datetime | None = None
        self._unsub = None

    async def async_check(self, session=None) -> None:
        if session is None:
            session = async_get_clientsession(self._hass)
        try:
            async with session.get(
                GITHUB_API_URL,
                headers={"Accept": "application/vnd.github.v3+json"},
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("ha_smart_display: GitHub API returned %s", resp.status)
                    return
                data = await resp.json()
            tag = data.get("tag_name", "")
            self.latest_version = tag.lstrip("v")
            self.release_html_url = data.get("html_url")
            assets = data.get("assets", [])
            apk = next((a for a in assets if a["name"].endswith(".apk")), None)
            self.latest_apk_url = apk["browser_download_url"] if apk else None
            self.last_checked = dt_util.now()
            _LOGGER.debug(
                "ha_smart_display: latest app version %s, apk_url=%s",
                self.latest_version, self.latest_apk_url,
            )
        except Exception as err:
            _LOGGER.warning("ha_smart_display: failed to check for updates: %s", err)

    async def async_start(self) -> None:
        await self.async_check()
        self._unsub = async_track_time_interval(
            self._hass,
            lambda _: self._hass.async_create_task(self.async_check()),
            UPDATE_CHECK_INTERVAL,
        )

    def stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
