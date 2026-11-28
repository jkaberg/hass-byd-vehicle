"""Tests for shared guest permission gating in hass-byd-vehicle (pyBYD #103)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from pybyd.models.vehicle import Vehicle

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.byd_vehicle import button, number, sensor  # noqa: E402
from custom_components.byd_vehicle.const import DOMAIN  # noqa: E402
from custom_components.byd_vehicle.coordinator import (  # noqa: E402
    BydDataUpdateCoordinator,
    BydGpsUpdateCoordinator,
)

_RANGE_BASIC_AND_CHARGE = [
    {
        "code": "2",
        "name": "Keys & Control",
        "childList": [{"code": "21", "name": "Basic control", "childList": []}],
    },
    {
        "code": "4",
        "name": "More control",
        "childList": [{"code": "41", "name": "Scheduled charging", "childList": []}],
    },
]


def test_coordinator_capability_available_enforces_guest_permissions() -> None:
    coordinator: Any = object.__new__(BydDataUpdateCoordinator)
    coordinator._car = SimpleNamespace(
        capabilities=SimpleNamespace(
            climate=True,
            lock=True,
            start_charge=True,
            battery_heat=True,
            location=True,
        )
    )
    # Owner: all True
    coordinator._vehicle = Vehicle.model_validate({"vin": "VIN", "empowerType": 2})
    assert coordinator.capability_available("climate") is True
    assert coordinator.capability_available("battery_heat") is True
    assert coordinator.capability_available("location") is True

    # Shared guest with empty rangeDetailList fails open rather than blocking all entities
    coordinator._vehicle = Vehicle.model_validate({"vin": "VIN", "empowerType": -1})
    assert coordinator.capability_available("climate") is True
    assert coordinator.capability_available("battery_heat") is True
    assert coordinator.capability_available("location") is True

    # Guest with only "21" and "41" (no "43" battery heat, no "31" location)
    coordinator._vehicle = Vehicle.model_validate(
        {
            "vin": "VIN",
            "empowerType": -1,
            "rangeDetailList": _RANGE_BASIC_AND_CHARGE,
        }
    )
    assert coordinator.capability_available("climate") is True
    assert coordinator.capability_available("lock") is True
    assert coordinator.capability_available("start_charge") is True
    assert coordinator.capability_available("battery_heat") is False
    assert coordinator.capability_available("location") is False


def test_read_only_capability_ignores_guest_permission() -> None:
    """A guest without "41" loses charge controls but keeps schedule state (#248)."""
    coordinator: Any = object.__new__(BydDataUpdateCoordinator)
    coordinator._car = SimpleNamespace(
        capabilities=SimpleNamespace(start_charge=True, battery_heat=True)
    )
    coordinator._vehicle = Vehicle.model_validate(
        {
            "vin": "VIN",
            "empowerType": -1,
            "rangeDetailList": [
                {
                    "code": "2",
                    "name": "Keys & Control",
                    "childList": [{"code": "21", "name": "Basic", "childList": []}],
                }
            ],
        }
    )
    assert coordinator.capability_supported("start_charge") is False
    assert coordinator.capability_supported("start_charge", guest_gated=False) is True
    assert coordinator.capability_supported("battery_heat", guest_gated=False) is True

    # the car's own capability still decides when guest gating is off
    coordinator._car = SimpleNamespace(capabilities=SimpleNamespace(start_charge=False))
    assert coordinator.capability_supported("start_charge", guest_gated=False) is False


@pytest.mark.asyncio
async def test_gps_coordinator_skips_poll_when_guest_lacks_31() -> None:
    gps_coord: Any = object.__new__(BydGpsUpdateCoordinator)
    gps_coord._vin = "TESTVIN123456"
    gps_coord._force_next_refresh = False
    gps_coord._polling_enabled = True
    gps_coord.data = None
    gps_coord._vehicle = Vehicle.model_validate(
        {
            "vin": "TESTVIN123456",
            "empowerType": -1,
            "rangeDetailList": _RANGE_BASIC_AND_CHARGE,
        }
    )
    car = SimpleNamespace(update_gps=AsyncMock())
    gps_coord._get_car = lambda: car

    snap = await gps_coord._async_update_data()
    assert snap.vehicle == gps_coord._vehicle
    car.update_gps.assert_not_awaited()


class _FakeCoord:
    def __init__(
        self,
        *,
        available_keys: set[str],
        perms: set[str],
    ) -> None:
        self.vin = "VIN"
        self.vehicle = SimpleNamespace(model_name="ATTO 3", brand_name="BYD")
        self.car = None
        self.inbox_enabled = False
        self._available = available_keys
        self._perms = perms
        self.async_get_standby_plans = AsyncMock(return_value=SimpleNamespace())

    def capability_available(self, key: str) -> bool:
        return key in self._available

    def capability_supported(self, key: str, *, guest_gated: bool = True) -> bool:
        # a guest without the permission reads as unsupported either way
        return key in self._available

    def guest_has_permission(self, code: str) -> bool:
        return code in self._perms

    async def async_maintenance_supported(self) -> bool:
        return False


@pytest.mark.asyncio
async def test_button_number_and_sensor_respect_guest_location_and_charging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "BydForcePollButton",
        "BydStartChargingButton",
        "BydFetchEnergyButton",
    ):
        monkeypatch.setattr(button, name, lambda *args, _n=name: _n)
    monkeypatch.setattr(
        number,
        "BydRealtimePollIntervalNumber",
        lambda *args: "realtime_interval",
    )
    monkeypatch.setattr(
        number,
        "BydGpsPollIntervalNumber",
        lambda *args: "gps_interval",
    )
    monkeypatch.setattr(
        sensor,
        "BydSensor",
        lambda coordinator, vin, vehicle, desc: desc.key,
    )
    monkeypatch.setattr(
        sensor,
        "BydNextClimatePlanSensor",
        lambda coordinator: "next_climate_plan",
    )

    # Guest without "41" (start_charge), without "31" (location), and without "21" (plans)
    coord = _FakeCoord(available_keys=set(), perms=set())
    entry = SimpleNamespace(entry_id="e")
    hass: Any = SimpleNamespace(
        data={
            DOMAIN: {
                "e": {
                    "coordinators": {"VIN": coord},
                    "gps_coordinators": {"VIN": SimpleNamespace()},
                }
            }
        }
    )

    btns: list[Any] = []
    nums: list[Any] = []
    sens: list[Any] = []
    await button.async_setup_entry(hass, cast(Any, entry), btns.extend)
    await number.async_setup_entry(hass, cast(Any, entry), nums.extend)
    await sensor.async_setup_entry(hass, cast(Any, entry), sens.extend)

    assert "BydStartChargingButton" not in btns
    assert "gps_interval" not in nums
    assert "gps_last_updated" not in sens
    assert "next_climate_plan" not in sens
    coord.async_get_standby_plans.assert_not_awaited()
