import logging

import voluptuous as vol

from homeassistant import config_entries, core, exceptions
from .tank import Tank
from .const import (
    CONF_AMBIENT_ENTITY,
    CONF_SERIAL,
    CONF_TANK_LITRES,
    CONF_TANK_SURFACE_M2,
    DEFAULT_TANK_LITRES,
    DEFAULT_TANK_SURFACE_M2,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Step 1: credentials + serial number
CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,
        vol.Required("serial_number"): str,
    }
)

# Step 2: optional physical tank properties used by the heat-loss calculator
TANK_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_TANK_LITRES, default=DEFAULT_TANK_LITRES): vol.Coerce(float),
        vol.Optional(CONF_TANK_SURFACE_M2, default=DEFAULT_TANK_SURFACE_M2): vol.Coerce(float),
        vol.Optional(CONF_AMBIENT_ENTITY, default=""): str,
    }
)


async def validate_credentials(hass: core.HomeAssistant, data: dict):
    """Validate that the supplied credentials allow a successful connection."""

    if not data.get("username"):
        raise InvalidUserName
    if not data.get("password"):
        raise InvalidPassword
    if not data.get("serial_number"):
        raise InvalidSerialNumber

    tank = Tank(hass, data["username"], data["password"], data["serial_number"])

    if not await tank.test_authentication():
        raise AuthenticationFailed

    if not await tank.test_connection():
        raise TankNotFound

    return {"title": data["serial_number"]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two-step config flow: credentials then optional tank properties."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        self._credentials: dict = {}

    # ------------------------------------------------------------------
    # Step 1 — credentials
    # ------------------------------------------------------------------

    async def async_step_user(self, user_input=None):
        """Collect and validate Mixergy account credentials."""
        errors = {}

        if user_input is not None:
            try:
                await validate_credentials(self.hass, user_input)
                self._credentials = user_input
                return await self.async_step_tank_options()
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except AuthenticationFailed:
                errors["base"] = "invalid_auth"
            except TankNotFound:
                errors["base"] = "tank_not_found"
            except InvalidUserName:
                errors["username"] = "cannot_connect"
            except InvalidPassword:
                errors["password"] = "cannot_connect"
            except InvalidSerialNumber:
                errors["serial_number"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during credential validation")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=CREDENTIALS_SCHEMA,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 2 — tank physical properties (heat-loss configuration)
    # ------------------------------------------------------------------

    async def async_step_tank_options(self, user_input=None):
        """Collect optional tank physical properties for heat-loss tracking."""
        errors = {}

        if user_input is not None:
            combined = {**self._credentials, **user_input}
            return self.async_create_entry(
                title=self._credentials["serial_number"],
                data=combined,
            )

        return self.async_show_form(
            step_id="tank_options",
            data_schema=TANK_OPTIONS_SCHEMA,
            errors=errors,
        )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we could not reach the Mixergy API."""

class AuthenticationFailed(exceptions.HomeAssistantError):
    """Error to indicate authentication failed."""

class TankNotFound(exceptions.HomeAssistantError):
    """Error to indicate we could not find a tank with the given serial number."""

class InvalidUserName(exceptions.HomeAssistantError):
    """Error to indicate an invalid / empty username."""

class InvalidPassword(exceptions.HomeAssistantError):
    """Error to indicate an invalid / empty password."""

class InvalidSerialNumber(exceptions.HomeAssistantError):
    """Error to indicate an invalid / empty serial number."""