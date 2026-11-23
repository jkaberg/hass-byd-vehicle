"""A car asleep at setup must not block the config entry (#238)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from pybyd import BydApiError, BydDataUnavailableError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.byd_vehicle.coordinator import (  # noqa: E402
    BydDataUpdateCoordinator,
)


async def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


def _coordinator(realtime_error: Exception) -> Any:
    async def update_realtime() -> None:
        raise realtime_error

    car = SimpleNamespace(
        update_realtime=update_realtime,
        update_charging=_noop,
        state=SimpleNamespace(realtime=None, hvac=None),
    )
    coordinator: Any = object.__new__(BydDataUpdateCoordinator)
    coordinator._vin = "TESTVIN0000000001"
    coordinator.data = None
    coordinator.update_pending = False
    coordinator._polling_enabled = True
    coordinator._force_next_refresh = False
    coordinator._car = car
    coordinator._realtime_endpoint_unsupported = False
    coordinator._api = SimpleNamespace(
        async_refresh_inbox=_noop, debug_dumps_enabled=False
    )
    coordinator._should_fetch_hvac = lambda *_a, **_k: False
    coordinator._async_refresh_standby_plans = _noop
    coordinator._async_refresh_ota = _noop
    coordinator._async_refresh_maintenance = _noop
    coordinator._schedule_hvac_final_reconcile_if_needed = lambda *_a: None
    coordinator._apply_charge_cadence = lambda *_a: None
    return coordinator


def test_asleep_car_without_realtime_sets_up() -> None:
    coordinator = _coordinator(
        BydDataUnavailableError("no usable data", code="not_ready", endpoint="rt")
    )

    snapshot = asyncio.run(coordinator._async_update_data())

    assert snapshot.realtime is None


def test_failed_realtime_fetch_still_fails() -> None:
    error = BydApiError("Service error(1008)", code="1008", endpoint="rt")
    coordinator = _coordinator(error)

    with pytest.raises(UpdateFailed, match="no data returned"):
        asyncio.run(coordinator._async_update_data())
