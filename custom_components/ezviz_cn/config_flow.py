"""Config flow for EZVIZ."""

from collections.abc import Mapping
import logging
from typing import TYPE_CHECKING, Any

from pyezvizapi.client import EzvizClient
from pyezvizapi.exceptions import (
    AuthTestResultFailed,
    EzvizAuthVerificationCode,
    InvalidHost,
    InvalidURL,
    PyEzvizError,
)
from pyezvizapi.test_cam_rtsp import TestRTSPAuth
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_CUSTOMIZE,
    CONF_IP_ADDRESS,
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_TYPE,
    CONF_URL,
    CONF_USERNAME,
)
from homeassistant.core import callback

from .const import (
    ATTR_SERIAL,
    ATTR_TYPE_CAMERA,
    ATTR_TYPE_CLOUD,
    CHINA_URL,
    CONF_FFMPEG_ARGUMENTS,
    CONF_RFSESSION_ID,
    CONF_SESSION_ID,
    DEFAULT_CAMERA_USERNAME,
    DEFAULT_FFMPEG_ARGUMENTS,
    DEFAULT_TIMEOUT,
    DOMAIN,
    EU_URL,
    RUSSIA_URL,
)
from .coordinator import EzvizConfigEntry

_LOGGER = logging.getLogger(__name__)
DEFAULT_OPTIONS = {
    CONF_FFMPEG_ARGUMENTS: DEFAULT_FFMPEG_ARGUMENTS,
    CONF_TIMEOUT: DEFAULT_TIMEOUT,
}
CONF_SMS_CODE = "sms_code"


def _validate_and_create_auth(data: dict) -> dict[str, Any]:
    """Try to login to EZVIZ cloud account and return token."""
    # Verify cloud credentials by attempting a login request with username and password.
    # Return login token.

    ezviz_client = EzvizClient(
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        data[CONF_URL],
        data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
    )

    ezviz_token = ezviz_client.login(data.get(CONF_SMS_CODE))

    return {
        CONF_SESSION_ID: ezviz_token[CONF_SESSION_ID],
        CONF_RFSESSION_ID: ezviz_token[CONF_RFSESSION_ID],
        CONF_URL: ezviz_token["api_url"],
        CONF_TYPE: ATTR_TYPE_CLOUD,
    }


def _test_camera_rtsp_creds(data: dict) -> None:
    """Try DESCRIBE on RTSP camera with credentials."""

    test_rtsp = TestRTSPAuth(
        data[CONF_IP_ADDRESS], data[CONF_USERNAME], data[CONF_PASSWORD]
    )

    test_rtsp.main()


class EzvizConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EZVIZ."""

    VERSION = 1

    ip_address: str
    username: str | None
    password: str | None
    auth_input: dict[str, Any] | None = None
    reauth_entry: EzvizConfigEntry | None = None
    unique_id: str

    async def _async_validate_cloud_auth(
        self,
        user_input: dict[str, Any],
    ) -> ConfigFlowResult:
        """Validate cloud auth input and create or update a config entry."""
        try:
            auth_data = await self.hass.async_add_executor_job(
                _validate_and_create_auth, user_input
            )

        except InvalidURL:
            return self.async_show_cloud_auth_form("invalid_host")

        except InvalidHost:
            return self.async_show_cloud_auth_form("cannot_connect")

        except EzvizAuthVerificationCode:
            self.auth_input = dict(user_input)
            return await self.async_step_mfa()

        except PyEzvizError:
            if CONF_SMS_CODE in user_input:
                return self.async_show_mfa_form("invalid_auth")
            return self.async_show_cloud_auth_form("invalid_auth")

        except Exception:
            _LOGGER.exception("Unexpected exception")
            return self.async_abort(reason="unknown")

        if self.reauth_entry is not None:
            return self.async_update_reload_and_abort(
                self.reauth_entry,
                data=auth_data,
            )

        return self.async_create_entry(
            title=user_input[CONF_USERNAME],
            data=auth_data,
            options=DEFAULT_OPTIONS,
        )

    @callback
    def async_show_cloud_auth_form(
        self,
        error: str,
    ) -> ConfigFlowResult:
        """Redisplay the current cloud auth form with an error."""
        errors = {"base": error}
        if self.reauth_entry is not None:
            data_schema = vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME, default=self.reauth_entry.title
                    ): vol.In([self.reauth_entry.title]),
                    vol.Required(CONF_PASSWORD): str,
                }
            )
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=data_schema,
                errors=errors,
            )

        if self.auth_input and self.auth_input.get(CONF_URL) == CONF_CUSTOMIZE:
            return self.async_show_form(
                step_id="user_custom_url",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_URL, default=CHINA_URL): str,
                    }
                ),
                errors=errors,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_URL, default=CHINA_URL): vol.In(
                        [CHINA_URL, EU_URL, RUSSIA_URL, CONF_CUSTOMIZE]
                    ),
                }
            ),
            errors=errors,
        )

    @callback
    def async_show_mfa_form(self, error: str | None = None) -> ConfigFlowResult:
        """Show the MFA verification code form."""
        return self.async_show_form(
            step_id="mfa",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SMS_CODE): str,
                }
            ),
            errors={"base": error} if error else {},
        )

    async def _validate_and_create_camera_rtsp(self, data: dict) -> ConfigFlowResult:
        """Try DESCRIBE on RTSP camera with credentials."""

        # Get EZVIZ cloud credentials from config entry
        ezviz_token = {
            CONF_SESSION_ID: None,
            CONF_RFSESSION_ID: None,
            "api_url": None,
        }
        ezviz_timeout = DEFAULT_TIMEOUT

        for item in self._async_current_entries():
            if item.data.get(CONF_TYPE) == ATTR_TYPE_CLOUD:
                ezviz_token = {
                    CONF_SESSION_ID: item.data.get(CONF_SESSION_ID),
                    CONF_RFSESSION_ID: item.data.get(CONF_RFSESSION_ID),
                    "api_url": item.data.get(CONF_URL),
                }
                ezviz_timeout = item.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)

        # Abort flow if user removed cloud account before adding camera.
        if ezviz_token.get(CONF_SESSION_ID) is None:
            return self.async_abort(reason="ezviz_cloud_account_missing")

        ezviz_client = EzvizClient(token=ezviz_token, timeout=ezviz_timeout)

        def _login_wake_and_test() -> None:
            # Login to create EZVIZ API instance.
            ezviz_client.login()
            # Wake hibernating camera.
            ezviz_client.get_detection_sensibility(data[ATTR_SERIAL])
            # Attempt an authenticated RTSP DESCRIBE request.
            _test_camera_rtsp_creds(data)

        await self.hass.async_add_executor_job(_login_wake_and_test)

        return self.async_create_entry(
            title=data[ATTR_SERIAL],
            data={
                CONF_USERNAME: data[CONF_USERNAME],
                CONF_PASSWORD: data[CONF_PASSWORD],
                CONF_TYPE: ATTR_TYPE_CAMERA,
            },
            options=DEFAULT_OPTIONS,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: EzvizConfigEntry,
    ) -> EzvizOptionsFlowHandler:
        """Get the options flow for this handler."""
        return EzvizOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by the user."""

        # Check if EZVIZ cloud account is present in entry config,
        # abort if already configured.
        for item in self._async_current_entries():
            if item.data.get(CONF_TYPE) == ATTR_TYPE_CLOUD:
                return self.async_abort(reason="already_configured_account")

        errors = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()
            self.auth_input = dict(user_input)

            if user_input[CONF_URL] == CONF_CUSTOMIZE:
                self.username = user_input[CONF_USERNAME]
                self.password = user_input[CONF_PASSWORD]
                return await self.async_step_user_custom_url()

            return await self._async_validate_cloud_auth(user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_URL, default=CHINA_URL): vol.In(
                    [CHINA_URL, EU_URL, RUSSIA_URL, CONF_CUSTOMIZE]
                ),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_user_custom_url(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by the user for custom region url."""
        errors = {}

        if user_input is not None:
            user_input[CONF_USERNAME] = self.username
            user_input[CONF_PASSWORD] = self.password
            self.auth_input = dict(user_input)

            return await self._async_validate_cloud_auth(user_input)

        data_schema_custom_url = vol.Schema(
            {
                vol.Required(CONF_URL, default=CHINA_URL): str,
            }
        )

        return self.async_show_form(
            step_id="user_custom_url", data_schema=data_schema_custom_url, errors=errors
        )

    async def async_step_mfa(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the MFA verification code step."""
        if self.auth_input is None:
            return await self.async_step_user()

        if user_input is not None:
            auth_input = dict(self.auth_input)
            auth_input[CONF_SMS_CODE] = user_input[CONF_SMS_CODE]
            return await self._async_validate_cloud_auth(auth_input)

        return self.async_show_mfa_form()

    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle a flow for discovered camera without rtsp config entry."""

        await self.async_set_unique_id(discovery_info[ATTR_SERIAL])
        self._abort_if_unique_id_configured()

        if TYPE_CHECKING:
            # A unique ID is passed in via the discovery info
            assert self.unique_id is not None
        self.context["title_placeholders"] = {ATTR_SERIAL: self.unique_id}
        self.ip_address = discovery_info[CONF_IP_ADDRESS]

        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm and create entry from discovery step."""
        errors = {}

        if user_input is not None:
            user_input[ATTR_SERIAL] = self.unique_id
            user_input[CONF_IP_ADDRESS] = self.ip_address
            try:
                return await self._validate_and_create_camera_rtsp(user_input)

            except (InvalidHost, InvalidURL):
                errors["base"] = "invalid_host"

            except EzvizAuthVerificationCode:
                errors["base"] = "mfa_required"

            except (PyEzvizError, AuthTestResultFailed):
                errors["base"] = "invalid_auth"

            except Exception:
                _LOGGER.exception("Unexpected exception")
                return self.async_abort(reason="unknown")

        discovered_camera_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=DEFAULT_CAMERA_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="confirm",
            data_schema=discovered_camera_schema,
            errors=errors,
            description_placeholders={
                ATTR_SERIAL: self.unique_id,
                CONF_IP_ADDRESS: self.ip_address,
            },
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a flow for reauthentication with password."""

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a Confirm flow for reauthentication with password."""
        errors = {}
        entry = None

        for item in self._async_current_entries():
            if item.data.get(CONF_TYPE) == ATTR_TYPE_CLOUD:
                self.context["title_placeholders"] = {ATTR_SERIAL: item.title}
                entry = await self.async_set_unique_id(item.title)
                self.reauth_entry = entry

        if not entry:
            return self.async_abort(reason="ezviz_cloud_account_missing")

        if user_input is not None:
            user_input[CONF_URL] = entry.data[CONF_URL]
            self.auth_input = dict(user_input)
            return await self._async_validate_cloud_auth(user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=entry.title): vol.In([entry.title]),
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=data_schema,
            errors=errors,
        )


class EzvizOptionsFlowHandler(OptionsFlowWithReload):
    """Handle EZVIZ client options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage EZVIZ options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = vol.Schema(
            {
                vol.Optional(
                    CONF_TIMEOUT,
                    default=self.config_entry.options.get(
                        CONF_TIMEOUT, DEFAULT_TIMEOUT
                    ),
                ): int,
                vol.Optional(
                    CONF_FFMPEG_ARGUMENTS,
                    default=self.config_entry.options.get(
                        CONF_FFMPEG_ARGUMENTS, DEFAULT_FFMPEG_ARGUMENTS
                    ),
                ): str,
            }
        )

        return self.async_show_form(step_id="init", data_schema=options)
