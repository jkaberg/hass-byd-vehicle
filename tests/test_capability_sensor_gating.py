"""Tests for capability-based sensor, smart-charging, and OTA preflight gating."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.byd_vehicle import (  # noqa: E402
    binary_sensor,
    sensor,
    switch,
    time,
)
from custom_components.byd_vehicle.const import DOMAIN  # noqa: E402
from custom_components.byd_vehicle.coordinator import (  # noqa: E402
    BydDataUpdateCoordinator,
)


def test_capability_supported_only_blocks_explicit_false() -> None:
    coordinator: Any = object.__new__(BydDataUpdateCoordinator)
    coordinator._car = None
    assert coordinator.capability_supported("health_oil_pressure") is True

    coordinator._car = SimpleNamespace(
        capabilities=SimpleNamespace(
            health_oil_pressure=False,
            health_coolant=None,
            health_abs=True,
        )
    )
    assert coordinator.capability_supported("health_oil_pressure") is False
    assert coordinator.capability_supported("health_coolant") is True
    assert coordinator.capability_supported("health_abs") is True


@pytest.mark.asyncio
async def test_async_ota_supported_short_circuits_when_learn_info_or_cap_false() -> None:
    coordinator: Any = object.__new__(BydDataUpdateCoordinator)
    coordinator._ota_probe = asyncio.Lock()
    coordinator._ota_supported = None
    coordinator._car = SimpleNamespace(capabilities=SimpleNamespace(mobile_ota=True))
    coordinator._vehicle = SimpleNamespace(
        vehicle_fun_learn_info={"otaUpgrade": 0},
        ota_upgrade_supported=False,
    )
    coordinator.async_get_ota = AsyncMock()

    assert await coordinator.async_ota_supported() is False
    coordinator.async_get_ota.assert_not_awaited()

    coordinator._ota_supported = None
    coordinator._vehicle = SimpleNamespace(
        vehicle_fun_learn_info={"otaUpgrade": 1},
        ota_upgrade_supported=True,
    )
    coordinator._car = SimpleNamespace(capabilities=SimpleNamespace(mobile_ota=False))
    assert await coordinator.async_ota_supported() is False
    coordinator.async_get_ota.assert_not_awaited()


class _FakeCoordinator:
    def __init__(
        self,
        *,
        supported_overrides: dict[str, bool] | None = None,
        available_keys: set[str] | None = None,
    ) -> None:
        self.vin = "VIN"
        self.vehicle = SimpleNamespace(model_name="ATTO 3", brand_name="BYD")
        self.inbox_enabled = False
        self._supported = supported_overrides or {}
        self._available = available_keys or set()

    def capability_supported(self, key: str) -> bool:
        return self._supported.get(key, True)

    def capability_available(self, key: str) -> bool:
        return key in self._available

    async def async_ota_supported(self) -> bool:
        return False

    async def async_get_standby_plans(self) -> None:
        return None


@pytest.mark.asyncio
async def test_binary_sensor_skips_unsupported_dtc_tpms_and_charging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        binary_sensor,
        "BydBinarySensor",
        lambda coordinator, vin, vehicle, desc: desc.key,
    )
    coord = _FakeCoordinator(
        supported_overrides={
            "health_oil_pressure": False,
            "health_coolant": False,
            "tpms": False,
            "start_charge": False,
        }
    )
    entry = SimpleNamespace(entry_id="e")
    hass: Any = SimpleNamespace(data={DOMAIN: {"e": {"coordinators": {"VIN": coord}}}})
    added: list[Any] = []
    await binary_sensor.async_setup_entry(hass, cast(Any, entry), added.extend)

    assert "oil_pressure_system" not in added
    assert "ect" not in added
    assert "rapid_tire_leak" not in added
    assert "left_front_tire_status" not in added
    assert "scheduled_charge_enabled" not in added
    assert "abs_warning" in added


@pytest.mark.asyncio
async def test_sensor_skips_direct_tpms_and_charging_when_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sensor,
        "BydSensor",
        lambda coordinator, vin, vehicle, desc: desc.key,
    )
    coord = _FakeCoordinator(
        supported_overrides={
            "direct_tpms": False,
            "start_charge": False,
        }
    )
    entry = SimpleNamespace(entry_id="e")
    hass: Any = SimpleNamespace(data={DOMAIN: {"e": {"coordinators": {"VIN": coord}}}})
    added: list[Any] = []
    await sensor.async_setup_entry(hass, cast(Any, entry), added.extend)

    assert "left_front_tire_pressure" not in added
    assert "right_rear_tire_pressure" not in added
    assert "scheduled_charge_start_time" not in added
    assert "elec_percent" in added


@pytest.mark.asyncio
async def test_switch_and_time_gate_smart_charging_on_start_charge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for cls_name in (
        "BydDisablePollingSwitch",
        "BydScheduleEnabledSwitch",
        "BydChargeToFullSwitch",
        "BydRepeatDailySwitch",
    ):
        monkeypatch.setattr(switch, cls_name, lambda *args, _n=cls_name: _n)
    for cls_name in ("BydStartTimeEntity", "BydEndTimeEntity"):
        monkeypatch.setattr(time, cls_name, lambda *args, _n=cls_name: _n)

    entry = SimpleNamespace(entry_id="e")

    # Without start_charge
    coord_no = _FakeCoordinator(available_keys=set())
    hass_no: Any = SimpleNamespace(
        data={DOMAIN: {"e": {"coordinators": {"VIN": coord_no}}}}
    )
    sw_no: list[Any] = []
    tm_no: list[Any] = []
    await switch.async_setup_entry(hass_no, cast(Any, entry), sw_no.extend)
    await time.async_setup_entry(hass_no, cast(Any, entry), tm_no.extend)
    assert sw_no == ["BydDisablePollingSwitch"]
    assert tm_no == []

    # With start_charge
    coord_yes = _FakeCoordinator(available_keys={"start_charge"})
    hass_yes: Any = SimpleNamespace(
        data={DOMAIN: {"e": {"coordinators": {"VIN": coord_yes}}}}
    )
    sw_yes: list[Any] = []
    tm_yes: list[Any] = []
    await switch.async_setup_entry(hass_yes, cast(Any, entry), sw_yes.extend)
    await time.async_setup_entry(hass_yes, cast(Any, entry), tm_yes.extend)
    assert "BydScheduleEnabledSwitch" in sw_yes
    assert "BydStartTimeEntity" in tm_yes
