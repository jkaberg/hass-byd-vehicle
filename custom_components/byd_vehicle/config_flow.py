"""Config flow for BYD Vehicle."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pybyd import BydApiError, BydAuthenticationError, BydClient, BydTransportError
from pybyd.config import BydConfig

from .const import (
    BASE_URLS,
    CONF_BASE_URL,
    CONF_CONTROL_PIN,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_PROFILE,
    CONF_GPS_ACTIVE_INTERVAL,
    CONF_GPS_INACTIVE_INTERVAL,
    CONF_GPS_POLL_INTERVAL,
    CONF_LANGUAGE,
    CONF_POLL_INTERVAL,
    CONF_SMART_GPS_POLLING,
    COUNTRY_OPTIONS,
    DEFAULT_COUNTRY,
    DEFAULT_GPS_ACTIVE_INTERVAL,
    DEFAULT_GPS_INACTIVE_INTERVAL,
    DEFAULT_GPS_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SMART_GPS_POLLING,
    DOMAIN,
)
from .device_fingerprint import generate_device_profile

_LOGGER = logging.getLogger(__name__)


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    session = async_get_clientsession(hass)
    country_name = data[CONF_COUNTRY_CODE]
    country_code, language = COUNTRY_OPTIONS[country_name]
    time_zone = hass.config.time_zone or "UTC"
    config = BydConfig(
        username=data["username"],
        password=data["password"],
        base_url=BASE_URLS[data[CONF_BASE_URL]],
        country_code=country_code,
        language=language,
        time_zone=time_zone,
        control_pin=data.get(CONF_CONTROL_PIN) or None,
    )
    async with BydClient(config, session=session) as client:
        await client.login()
        await client.get_vehicles()


class BydVehicleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BYD Vehicle."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _validate_input(self.hass, user_input)
            except BydAuthenticationError:
                errors["base"] = "invalid_auth"
            except (BydApiError, BydTransportError) as exc:
                _LOGGER.warning("BYD API error during validation: %s", exc)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during validation")
                errors["base"] = "unknown"
            else:
                base_url = BASE_URLS[user_input[CONF_BASE_URL]]
                country_name = user_input[CONF_COUNTRY_CODE]
                country_code, language = COUNTRY_OPTIONS[country_name]
                await self.async_set_unique_id(f"{user_input['username']}@{base_url}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input["username"],
                    data={
                        "username": user_input["username"],
                        "password": user_input["password"],
                        CONF_BASE_URL: base_url,
                        CONF_COUNTRY_CODE: country_code,
                        CONF_LANGUAGE: language,
                        CONF_DEVICE_PROFILE: generate_device_profile(),
                        CONF_CONTROL_PIN: user_input.get(CONF_CONTROL_PIN, ""),
                    },
                    options={
                        CONF_POLL_INTERVAL: user_input[CONF_POLL_INTERVAL],
                        CONF_GPS_POLL_INTERVAL: user_input[CONF_GPS_POLL_INTERVAL],
                        CONF_SMART_GPS_POLLING: user_input[CONF_SMART_GPS_POLLING],
                        CONF_GPS_ACTIVE_INTERVAL: user_input[CONF_GPS_ACTIVE_INTERVAL],
                        CONF_GPS_INACTIVE_INTERVAL: user_input[
                            CONF_GPS_INACTIVE_INTERVAL
                        ],
                    },
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL, default="Europe"): vol.In(list(BASE_URLS)),
                vol.Required("username"): str,
                vol.Required("password"): str,
                vol.Optional(CONF_CONTROL_PIN, default=""): str,
                vol.Required(
                    CONF_COUNTRY_CODE,
                    default=DEFAULT_COUNTRY,
                ): vol.In(list(COUNTRY_OPTIONS)),
                vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): int,
                vol.Optional(
                    CONF_GPS_POLL_INTERVAL, default=DEFAULT_GPS_POLL_INTERVAL
                ): int,
                vol.Optional(
                    CONF_SMART_GPS_POLLING, default=DEFAULT_SMART_GPS_POLLING
                ): bool,
                vol.Optional(
                    CONF_GPS_ACTIVE_INTERVAL, default=DEFAULT_GPS_ACTIVE_INTERVAL
                ): int,
                vol.Optional(
                    CONF_GPS_INACTIVE_INTERVAL, default=DEFAULT_GPS_INACTIVE_INTERVAL
                ): int,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_reauth(self, _: dict[str, Any]) -> dict[str, Any]:
        return await self.async_step_user()

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return BydVehicleOptionsFlow(config_entry)


class BydVehicleOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for BYD Vehicle."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_POLL_INTERVAL,
                    default=self._config_entry.options.get(
                        CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                    ),
                ): int,
                vol.Optional(
                    CONF_GPS_POLL_INTERVAL,
                    default=self._config_entry.options.get(
                        CONF_GPS_POLL_INTERVAL, DEFAULT_GPS_POLL_INTERVAL
                    ),
                ): int,
                vol.Optional(
                    CONF_SMART_GPS_POLLING,
                    default=self._config_entry.options.get(
                        CONF_SMART_GPS_POLLING, DEFAULT_SMART_GPS_POLLING
                    ),
                ): bool,
                vol.Optional(
                    CONF_GPS_ACTIVE_INTERVAL,
                    default=self._config_entry.options.get(
                        CONF_GPS_ACTIVE_INTERVAL, DEFAULT_GPS_ACTIVE_INTERVAL
                    ),
                ): int,
                vol.Optional(
                    CONF_GPS_INACTIVE_INTERVAL,
                    default=self._config_entry.options.get(
                        CONF_GPS_INACTIVE_INTERVAL, DEFAULT_GPS_INACTIVE_INTERVAL
                    ),
                ): int,
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)
