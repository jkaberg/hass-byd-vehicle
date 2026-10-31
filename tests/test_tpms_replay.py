"""Native HA 2026.10.2 lifecycle replay; no BYD account or network calls.

Run with the integration checkout on PYTHONPATH. Dependencies are the integration's
pybyd pin, Home Assistant and pytest/pytest-asyncio. A standalone entity component
is used; the resulting no-config-entry device warning is a harness limitation.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest
import pytest_asyncio
from homeassistant import loader
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry,
    entity,
    entity_registry,
    frame,
    restore_state,
)
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pybyd import VehicleSnapshot
from pybyd.models.realtime import VehicleRealtimeData
from pybyd.models.vehicle import Vehicle

from custom_components.byd_vehicle.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    BydBinarySensor,
)

CORNERS = (
    "left_front_tire_status",
    "right_front_tire_status",
    "left_rear_tire_status",
    "right_rear_tire_status",
)
FIELDS = (*CORNERS, "tirepressure_system")
HEALTHY = dict.fromkeys(FIELDS, 0)
LOGGER = logging.getLogger(__name__)


@pytest_asyncio.fixture
async def runtime(tmp_path):
    """Load the actual HA registries, entity platform and restore-state helper."""
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    frame.async_setup(hass)
    entity.async_setup(hass)
    device_registry.async_setup(hass)
    await device_registry.async_load(hass)
    await entity_registry.async_load(hass)
    await restore_state.async_load(hass)
    component = EntityComponent(LOGGER, "binary_sensor", hass)
    await component.async_setup({})
    try:
        yield hass, component
    finally:
        await hass.async_stop()


async def add_sensor(runtime, key, *, vin="TEST0000000000001", initial=None):
    hass, component = runtime
    coordinator = DataUpdateCoordinator(
        hass, LOGGER, config_entry=None, name=f"TPMS replay {vin}"
    )
    vehicle = Vehicle(vin=vin, model_name="Synthetic BYD")
    description = next(d for d in BINARY_SENSOR_DESCRIPTIONS if d.key == key)
    sensor = BydBinarySensor(
        coordinator,
        vin,
        vehicle,
        replace(description, entity_registry_enabled_default=True),
    )
    sensor.entity_id = f"binary_sensor.{vin.lower()}_{key}"
    coordinator.async_set_updated_data(
        VehicleSnapshot(
            vehicle=vehicle,
            realtime=(
                VehicleRealtimeData.model_validate(initial)
                if initial is not None
                else None
            ),
        )
    )
    await component.async_add_entities([sensor])
    assert hass.states.get(sensor.entity_id) is not None, "HA failed to add entity"
    return sensor, coordinator, vehicle


async def publish(runtime, item, payload, expected):
    hass, _ = runtime
    sensor, coordinator, vehicle = item
    coordinator.async_set_updated_data(
        VehicleSnapshot(
            vehicle=vehicle,
            realtime=(
                VehicleRealtimeData.model_validate(payload)
                if payload is not None
                else None
            ),
        )
    )
    await hass.async_block_till_done()
    state = hass.states.get(sensor.entity_id)
    assert state is not None
    print(
        f"{sensor.entity_id}: payload={payload!r}; "
        f"state={state.state}; expected={expected}"
    )
    assert state.state == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("corner", CORNERS)
async def test_fault_clears_and_recurs(runtime, corner):
    item = await add_sensor(runtime, corner)
    await publish(runtime, item, HEALTHY, STATE_UNKNOWN)
    await publish(runtime, item, {**HEALTHY, corner: 1}, STATE_ON)
    await publish(runtime, item, HEALTHY, STATE_OFF)
    await publish(runtime, item, HEALTHY, STATE_OFF)
    await publish(runtime, item, {}, STATE_OFF)
    await publish(runtime, item, {**HEALTHY, corner: 2}, STATE_ON)


@pytest.mark.asyncio
async def test_initial_fault_clears(runtime):
    item = await add_sensor(runtime, CORNERS[0], initial={**HEALTHY, CORNERS[0]: 1})
    hass, _ = runtime
    assert hass.states.get(item[0].entity_id).state == STATE_ON
    await publish(runtime, item, HEALTHY, STATE_OFF)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", FIELDS)
async def test_partial_or_negative_does_not_clear(runtime, missing):
    item = await add_sensor(runtime, CORNERS[0])
    await publish(runtime, item, {**HEALTHY, CORNERS[0]: 1}, STATE_ON)
    await publish(
        runtime, item, {k: v for k, v in HEALTHY.items() if k != missing}, STATE_ON
    )
    await publish(runtime, item, {**HEALTHY, missing: -1}, STATE_ON)
    await publish(runtime, item, None, STATE_UNAVAILABLE)
    await publish(runtime, item, {}, STATE_ON)


@pytest.mark.asyncio
async def test_history_is_per_vehicle(runtime):
    first = await add_sensor(runtime, CORNERS[0])
    second = await add_sensor(runtime, CORNERS[0], vin="TEST0000000000002")
    await publish(runtime, first, {**HEALTHY, CORNERS[0]: 1}, STATE_ON)
    await publish(runtime, second, HEALTHY, STATE_UNKNOWN)
    await publish(runtime, first, HEALTHY, STATE_OFF)
    await publish(runtime, second, HEALTHY, STATE_UNKNOWN)


@pytest.mark.asyncio
@pytest.mark.parametrize("initial", [{}, HEALTHY], ids=["partial", "healthy"])
async def test_restore_and_reload(runtime, initial):
    item = await add_sensor(runtime, CORNERS[0])
    await publish(runtime, item, {**HEALTHY, CORNERS[0]: 1}, STATE_ON)
    await item[0].async_remove()
    restored = await add_sensor(runtime, CORNERS[0], initial=initial)
    hass, _ = runtime
    expected = STATE_OFF if initial == HEALTHY else STATE_ON
    assert hass.states.get(restored[0].entity_id).state == expected
    await publish(runtime, restored, HEALTHY, STATE_OFF)
    await restored[0].async_remove()
    cleared = await add_sensor(runtime, CORNERS[0], initial={})
    assert hass.states.get(cleared[0].entity_id).state == STATE_OFF


@pytest.mark.asyncio
async def test_unrelated_warning_cache(runtime):
    item = await add_sensor(runtime, "braking_system")
    await publish(runtime, item, {"braking_system": 1}, STATE_ON)
    await publish(runtime, item, {}, STATE_ON)
    await publish(runtime, item, {"braking_system": 0}, STATE_OFF)
