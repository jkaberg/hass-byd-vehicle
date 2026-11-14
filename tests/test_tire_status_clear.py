"""Per-tyre status sensors clear once the car reports all zeros again (#203)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.byd_vehicle.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    BydBinarySensor,
)

_DESC = next(d for d in BINARY_SENSOR_DESCRIPTIONS if d.key == "left_front_tire_status")


def _realtime(left_front: int, system: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        left_front_tire_status=left_front,
        right_front_tire_status=0,
        left_rear_tire_status=0,
        right_rear_tire_status=0,
        tirepressure_system=system,
    )


def _sensor(obj: Any, last_is_on: bool | None) -> BydBinarySensor:
    sensor = BydBinarySensor.__new__(BydBinarySensor)
    sensor.entity_description = _DESC
    sensor._last_is_on = last_is_on

    def _source(_name: str) -> Any:
        return obj

    sensor._get_source_obj = _source  # type: ignore[method-assign,assignment]
    return sensor


def test_fault_passes_through() -> None:
    assert _sensor(_realtime(1), None)._resolve_value() is True


def test_all_zero_after_fault_clears() -> None:
    assert _sensor(_realtime(0), True)._resolve_value() is False


def test_all_zero_without_fault_stays_sentinel() -> None:
    assert _sensor(_realtime(0), None)._resolve_value() is None
    assert _sensor(_realtime(0), False)._resolve_value() is None


def test_system_flag_keeps_corner_off() -> None:
    assert _sensor(_realtime(0, system=1), True)._resolve_value() is False
