"""A rejected login keeps the form filled in and logs the server code (#250)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from pybyd.exceptions import BydAuthenticationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.byd_vehicle import config_flow  # noqa: E402
from custom_components.byd_vehicle.const import (  # noqa: E402
    CONF_CLIMATE_DURATION,
    CONF_CONTROL_PIN,
    CONF_COUNTRY_CODE,
    CONF_DEBUG_DUMPS,
    CONF_INBOX_NOTIFICATIONS,
    CONF_MQTT_ENABLED,
)

_INPUT: dict[str, Any] = {
    "username": "someone@example.com",
    "password": "secret",
    CONF_CONTROL_PIN: "",
    CONF_COUNTRY_CODE: "Austria",
    CONF_CLIMATE_DURATION: "20 min",
    CONF_MQTT_ENABLED: True,
    CONF_INBOX_NOTIFICATIONS: False,
    CONF_DEBUG_DUMPS: True,
}


def _defaults(schema: Any) -> dict[str, Any]:
    return {str(key): key.default() for key in schema.schema}


def test_defaults_from_input_maps_labels_back() -> None:
    defaults = config_flow._defaults_from_input(_INPUT)
    assert defaults[CONF_COUNTRY_CODE] == "AT"
    assert defaults[CONF_CLIMATE_DURATION] == 20
    assert defaults["username"] == "someone@example.com"


@pytest.mark.asyncio
async def test_rejected_login_keeps_input_and_logs_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    flow = config_flow.BydVehicleConfigFlow()
    flow.hass = cast(Any, object())
    error = BydAuthenticationError("Login failed: code=1001 message=bad", code="1001")
    with patch.object(config_flow, "_validate_input", AsyncMock(side_effect=error)):
        with caplog.at_level(logging.WARNING):
            result = await flow.async_step_user(dict(_INPUT))

    assert result["errors"] == {"base": "invalid_auth"}
    defaults = _defaults(result["data_schema"])
    assert defaults[CONF_COUNTRY_CODE] == "Austria"
    assert defaults["username"] == "someone@example.com"
    assert defaults["password"] == "secret"
    assert defaults[CONF_CLIMATE_DURATION] == "20 min"
    assert defaults[CONF_DEBUG_DUMPS] is True
    assert "code=1001" in caplog.text
    assert "secret" not in caplog.text
