"""Legacy ``total_*`` consumption sensors on real captures (#175, #181).

Needs Home Assistant and pyBYD installed. Run from the repository root with
``python -m pytest tests``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pybyd._validators import apply_realtime_filters
from pybyd.models.realtime import VehicleRealtimeData
from pybyd.models.vehicle import EnergyType

from custom_components.byd_vehicle.sensor import SENSOR_DESCRIPTIONS, BydSensor

# Shark 6 PHEV, Brazil (#175).
SHARK_BR = {
    "totalConsumption": "(6.7度+7.2升)/百公里",
    "totalConsumptionEn": "(6.7kW·h+7.2L)/100km",
    "totalEnergy": "6.7kW·h/100km+7.2L/100km",
}
# Seal BEV, UK, display set to miles (#181).
SEAL_UK = {
    "totalConsumption": "19.9度/百公里",
    "totalConsumptionEn": "19.9kW·h/100km",
    "totalEnergy": "32.0kW·h/100miles",
}
# HTTP poll answered while the car sleeps (#181).
ASLEEP_HTTP = {
    "powerSystem": 0,
    "totalEnergy": "--",
    "elecPercent": 0,
    "enduranceMileageV2Unit": "--",
    "nearestEnergyConsumptionUnit": "--",
    "nearestEnergyConsumption": "--",
    "recent50kmEnergy": "--",
    "totalMileageV2Unit": "--",
    "onlineState": 0,
}
# Not captured: a hybrid displaying miles, with a different figure per field.
HYBRID_MILES = {
    "totalConsumption": "(6.6度+7.1升)/百公里",
    "totalConsumptionEn": "(6.8kW·h+7.3L)/100km",
    "totalEnergy": "6.4kW·h/100miles+11.3L/100miles",
}
# Not captured: a pure-ICE car, whose only leg is fuel.
ICE = {
    "totalConsumption": "7.4升/百公里",
    "totalConsumptionEn": "7.4L/100km",
    "totalEnergy": "7.4L/100km",
}
# Not captured: efficiency units must not be shown as kWh/100km or L/100km.
EFFICIENCY_UNITS = dict.fromkeys(
    ("totalConsumption", "totalConsumptionEn", "totalEnergy"), "3.1mi/kW·h+39.2mpg"
)

KEYS = ("total_energy", "total_consumption", "total_consumption_en")
DESCRIPTIONS = {description.key: description for description in SENSOR_DESCRIPTIONS}
KWH = "kWh/100km"


def _fuel(value: float) -> dict[str, Any]:
    return {"fuel_consumption": value, "fuel_consumption_unit": "L/100km"}


# (state, unit, attributes without the VIN) per sensor key.
CASES = {
    "shark_br": (
        EnergyType.HYBRID,
        [SHARK_BR],
        dict.fromkeys(KEYS, (6.7, KWH, _fuel(7.2))),
    ),
    "shark_br_then_asleep": (
        EnergyType.HYBRID,
        [SHARK_BR, ASLEEP_HTTP],
        dict.fromkeys(KEYS, (6.7, KWH, _fuel(7.2))),
    ),
    # totalEnergy is per 100 miles on this car: 32.0 / 1.609344 = 19.9.
    "seal_uk": (EnergyType.EV, [SEAL_UK], dict.fromkeys(KEYS, (19.9, KWH, {}))),
    "seal_uk_then_asleep": (
        EnergyType.EV,
        [SEAL_UK, ASLEEP_HTTP],
        dict.fromkeys(KEYS, (19.9, KWH, {})),
    ),
    "hybrid_miles": (
        EnergyType.HYBRID,
        [HYBRID_MILES],
        {
            "total_energy": (4.0, KWH, _fuel(7.0)),
            "total_consumption": (6.6, KWH, _fuel(7.1)),
            "total_consumption_en": (6.8, KWH, _fuel(7.3)),
        },
    ),
    # A newer EV-only reading must not keep the previous fuel leg.
    "shark_br_then_ev_only": (
        EnergyType.HYBRID,
        [SHARK_BR, dict.fromkeys(SHARK_BR, "6.8kW·h/100km")],
        dict.fromkeys(KEYS, (6.8, KWH, {})),
    ),
    "ice": (EnergyType.ICE, [ICE], dict.fromkeys(KEYS, (None, KWH, _fuel(7.4)))),
    "efficiency_units": (
        EnergyType.HYBRID,
        [EFFICIENCY_UNITS],
        dict.fromkeys(KEYS, (None, KWH, {})),
    ),
}


def _sensors(
    energy_type: EnergyType, payloads: list[dict[str, Any]]
) -> dict[str, BydSensor]:
    """Build the sensors on *payloads*, filtered as pyBYD's state engine does."""
    realtime = None
    for raw in payloads:
        # A fresh copy, so no case can alter the shared captures.
        incoming = VehicleRealtimeData.model_validate(
            dict(raw), context={"energy_type": energy_type}
        )
        realtime = apply_realtime_filters(realtime, incoming)
    coordinator: Any = SimpleNamespace(data=SimpleNamespace(realtime=realtime))
    vehicle: Any = None
    return {
        key: BydSensor(coordinator, "VIN", vehicle, DESCRIPTIONS[key]) for key in KEYS
    }


@pytest.mark.parametrize(
    ("energy_type", "payloads", "expected"), list(CASES.values()), ids=list(CASES)
)
def test_legacy_consumption_sensors(
    energy_type: EnergyType,
    payloads: list[dict[str, Any]],
    expected: dict[str, tuple[Any, str, dict[str, Any]]],
) -> None:
    sensors = _sensors(energy_type, payloads)
    assert {
        key: (
            sensor.native_value,
            sensor.native_unit_of_measurement,
            {k: v for k, v in sensor.extra_state_attributes.items() if k != "vin"},
        )
        for key, sensor in sensors.items()
    } == expected
