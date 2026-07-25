"""Provides the ezviz DataUpdateCoordinator."""

import asyncio
from datetime import timedelta
import logging

from pyezvizapi.client import EzvizClient
from pyezvizapi.exceptions import (
    EzvizAuthTokenExpired,
    EzvizAuthVerificationCode,
    HTTPError,
    InvalidURL,
    PyEzvizError,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_RFSESSION_ID, CONF_SESSION_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

type EzvizConfigEntry = ConfigEntry[EzvizDataUpdateCoordinator]


class EzvizDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching EZVIZ data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: EzvizConfigEntry,
        *,
        api: EzvizClient,
        api_timeout: int,
    ) -> None:
        """Initialize global EZVIZ data updater."""
        self.ezviz_client = api
        self._api_timeout = api_timeout
        update_interval = timedelta(minutes=5)

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=update_interval,
        )

    def _persist_login_token(self) -> None:
        """Persist a token refreshed transparently by the API client."""
        token = self.ezviz_client.export_token()
        session_id = token.get(CONF_SESSION_ID)
        refresh_session_id = token.get(CONF_RFSESSION_ID)
        if not session_id or not refresh_session_id:
            return

        api_url = token.get("api_url", self.config_entry.data.get(CONF_URL))
        if (
            session_id == self.config_entry.data.get(CONF_SESSION_ID)
            and refresh_session_id == self.config_entry.data.get(CONF_RFSESSION_ID)
            and api_url == self.config_entry.data.get(CONF_URL)
        ):
            return

        data = {
            **self.config_entry.data,
            CONF_SESSION_ID: session_id,
            CONF_RFSESSION_ID: refresh_session_id,
            CONF_URL: api_url,
            CONF_USERNAME: self.config_entry.data.get(CONF_USERNAME),
            CONF_PASSWORD: self.config_entry.data.get(CONF_PASSWORD),
        }
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)

    async def _async_load_cameras(self, *, refresh: bool = False) -> dict:
        """Load cameras from the API."""
        return await self.hass.async_add_executor_job(
            self.ezviz_client.load_cameras, refresh
        )

    async def _async_update_data(self) -> dict:
        """Fetch data from EZVIZ."""
        try:
            async with asyncio.timeout(self._api_timeout):
                try:
                    cameras = await self._async_load_cameras()
                except (EzvizAuthTokenExpired, EzvizAuthVerificationCode) as error:
                    raise ConfigEntryAuthFailed from error
                except (InvalidURL, HTTPError, PyEzvizError) as error:
                    if self.data is not None:
                        _LOGGER.warning(
                            "Keeping previous EZVIZ data after API error: %s",
                            _error_text(error),
                        )
                        return self.data
                    raise UpdateFailed(
                        f"Invalid response from API: {_error_text(error)}"
                    ) from error

                self._persist_login_token()
                return cameras

        except TimeoutError as error:
            if self.data is not None:
                _LOGGER.warning("Keeping previous EZVIZ data after API timeout")
                return self.data
            raise UpdateFailed("EZVIZ API request timed out") from error


def _error_text(error: Exception) -> str:
    """Return a useful message even for exceptions without text."""
    return str(error).strip() or error.__class__.__name__
