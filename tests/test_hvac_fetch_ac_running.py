"""HVAC is fetched while the A/C runs with the car off (pyBYD #20, #91)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pybyd.models.hvac import HvacStatus
from pybyd.models.realtime import VehicleRealtimeData

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.byd_vehicle.coordinator import (  # noqa: E402
    BydDataUpdateCoordinator,
)

_should_fetch = BydDataUpdateCoordinator._should_fetch_hvac


def _snapshot(realtime: dict[str, Any], hvac: dict[str, Any]) -> Any:
    return SimpleNamespace(
        realtime=VehicleRealtimeData.model_validate(realtime),
        hvac=HvacStatus.model_validate(hvac),
    )


def _coordinator() -> Any:
    return SimpleNamespace(
        _is_vehicle_on_from_snapshot=lambda s: s.realtime.is_vehicle_on
    )


@pytest.mark.parametrize(
    ("realtime", "hvac", "fetch"),
    [
        # parked, A/C off: leave the car be
        ({"powerGear": 1, "airRunState": 2}, {"status": 2}, False),
        # climate plan running with the car off
        ({"powerGear": 1, "airRunState": 1}, {"status": 2}, True),
        # plan just ended, HVAC still says on: one more fetch to see it off
        ({"powerGear": 1, "airRunState": 2}, {"status": 1}, True),
        # car on: as before
        ({"powerGear": 3, "airRunState": 2}, {"status": 2}, True),
        # cars that don't report airRunState: as before
        ({"powerGear": 1}, {"status": 2}, False),
    ],
)
def test_should_fetch_hvac(
    realtime: dict[str, Any], hvac: dict[str, Any], fetch: bool
) -> None:
    assert _should_fetch(_coordinator(), _snapshot(realtime, hvac)) is fetch
