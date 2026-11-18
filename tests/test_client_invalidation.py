from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.byd_vehicle.const import (  # noqa: E402
    CONF_BASE_URL,
    CONF_DEVICE_PROFILE,
)
from custom_components.byd_vehicle.coordinator import BydApi  # noqa: E402


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
