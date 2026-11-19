from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pybyd import BydApiError  # noqa: E402

from custom_components.byd_vehicle.const import (  # noqa: E402
    CONF_BASE_URL,
    CONF_DEVICE_PROFILE,
)
from custom_components.byd_vehicle.coordinator import (  # noqa: E402
    BydApi,
    BydGpsUpdateCoordinator,
)


class _FakeClient:
    def __init__(self) -> None:
        self.closed = False

    async def async_close(self) -> None:
        self.closed = True


def test_invalidate_client_drops_cached_cars() -> None:
    """A car bound to a closed client must not outlive it."""
    hass: Any = SimpleNamespace(
        config=SimpleNamespace(time_zone="UTC", path=lambda *parts: "/tmp/byd")
    )
    entry: Any = SimpleNamespace(
        entry_id="entry",
        data={
            "username": "user",
            "password": "pass",
            CONF_BASE_URL: "https://example.invalid",
            CONF_DEVICE_PROFILE: {},
        },
        options={},
    )
    api = BydApi(hass, entry, session=None)
    client = _FakeClient()
    coordinator: Any = SimpleNamespace(_car=object())
    api._client = client
    api._coordinators = {"VIN": coordinator}

    asyncio.run(api._invalidate_client())

    assert client.closed
    assert api._client is None
    assert coordinator._car is None


class _LocationDenied(BydApiError):
    def __init__(self) -> None:
        Exception.__init__(self, "location permission denied")
        self.code = "8002"


class _FakeGpsApi:
    debug_dumps_enabled = False

    def __init__(self) -> None:
        self.resets = 0

    async def _invalidate_client(self) -> None:
        self.resets += 1


def test_gps_8002_resets_client_once_per_streak(caplog: Any) -> None:
    """Location permission off must not re-login on every GPS poll."""
    outcomes: list[Exception | None] = []

    async def update_gps() -> None:
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome

    car = SimpleNamespace(update_gps=update_gps, state=SimpleNamespace(gps=None))
    api = _FakeGpsApi()
    coordinator: Any = object.__new__(BydGpsUpdateCoordinator)
    coordinator._api = api
    coordinator._vin = "TESTVIN0000000001"
    coordinator._vehicle = None
    coordinator.data = object()
    coordinator._telemetry_coordinator = SimpleNamespace(car=car)
    coordinator._polling_enabled = True
    coordinator._force_next_refresh = False
    coordinator._location_denied = False

    def poll(outcome: Exception | None) -> None:
        outcomes.append(outcome)
        asyncio.run(coordinator._async_update_data())

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            poll(_LocationDenied())
    assert api.resets == 1
    warnings = [r.getMessage() for r in caplog.records]
    assert len(warnings) == 1
    assert "Privacy in the BYD app" in warnings[0]

    # A successful fetch ends the streak; the next 8002 resets again.
    poll(None)
    poll(_LocationDenied())
    assert api.resets == 2
