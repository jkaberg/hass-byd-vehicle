"""Configured HA lifecycle regression with a synthetic, network-blocked BYD cloud.

Real integration setup, platform forwarding, client/car/state engine, coordinators,
entity registry, services and config-entry reload run unchanged. Only client cloud
reads and authentication startup are replaced. A real aiohttp session fixture
replaces the HA session factory to avoid zeroconf/network bootstrapping. All
requests, socket connects, UDP sendto and DNS resolution are blocked during
integration execution. This is not a vehicle/cloud or browser-UI test.
"""

from __future__ import annotations

import logging
import socket
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import aiohttp
import pytest
import pytest_asyncio
from homeassistant import loader
from homeassistant.bootstrap import async_load_base_functionality
from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry
from pybyd import BydClient
from pybyd.client import SmartChargingSchedule
from pybyd.config import DeviceProfile
from pybyd.models.charging import ChargingStatus
from pybyd.models.energy import EnergyConsumption
from pybyd.models.gps import GpsInfo
from pybyd.models.hvac import HvacStatus
from pybyd.models.latest_config import VehicleCapabilities
from pybyd.models.realtime import VehicleRealtimeData
from pybyd.models.vehicle import Vehicle

DOMAIN = "byd_vehicle"
VINS = ("SYNTHETIC000000001", "SYNTHETIC000000002")
CORNERS = (
    "left_front_tire_status",
    "right_front_tire_status",
    "left_rear_tire_status",
    "right_rear_tire_status",
)
ALIASES = (
    "leftFrontTireStatus",
    "rightFrontTireStatus",
    "leftRearTireStatus",
    "rightRearTireStatus",
)
HEALTHY = dict.fromkeys((*ALIASES, "tirepressureSystem"), 0)
LOGGER = logging.getLogger("configured_tpms")


def blocked_network(*args, **kwargs):
    raise AssertionError("Configured replay forbids outbound network")


class SyntheticCloud:
    def __init__(self):
        self.payloads = {vin: dict(HEALTHY) for vin in VINS}
        self.reads = {vin: 0 for vin in VINS}

    async def start(self, client):
        LOGGER.debug("Synthetic cloud startup: no authentication or network")

    async def vehicles(self, client):
        return [
            Vehicle(vin=vin, model_name=f"Synthetic {index}")
            for index, vin in enumerate(VINS)
        ]

    async def realtime(self, client, vin):
        raw = dict(self.payloads[vin])
        self.reads[vin] += 1
        LOGGER.debug("Synthetic realtime response vin=%s raw=%r", vin, raw)
        return VehicleRealtimeData.model_validate(raw)

    async def capabilities(self, client, vin):
        return VehicleCapabilities(vin=vin)

    async def hvac(self, client, vin):
        return HvacStatus()

    async def charging(self, client, vin):
        return ChargingStatus(), SmartChargingSchedule(vin=vin)

    async def energy(self, client, vin):
        return EnergyConsumption()

    async def gps(self, client, vin):
        return GpsInfo()


@pytest_asyncio.fixture
async def configured(tmp_path, request):
    import custom_components.byd_vehicle as integration

    source_components = Path(integration.__file__).resolve().parent.parent
    (tmp_path / "custom_components").symlink_to(
        source_components, target_is_directory=True
    )
    hass = HomeAssistant(str(tmp_path))
    hass.config.skip_pip = True
    loader.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    await loader.async_get_custom_components(hass)
    assert await async_load_base_functionality(hass)
    cloud = SyntheticCloud()
    if getattr(request, "param", False):
        cloud.payloads[VINS[0]] = {**HEALTHY, ALIASES[0]: 1}
    methods = {
        "async_start": cloud.start,
        "get_vehicles": cloud.vehicles,
        "get_vehicle_realtime": cloud.realtime,
        "get_vehicle_capabilities": cloud.capabilities,
        "get_hvac_status": cloud.hvac,
        "get_charging_homepage": cloud.charging,
        "get_energy_consumption": cloud.energy,
        "get_gps_info": cloud.gps,
    }
    # Preserve BydClient method binding while the cloud object stores fixtures.
    wrappers = {}
    for name, bound in methods.items():

        async def wrapper(client, *args, _bound=bound, **kwargs):
            return await _bound(client, *args, **kwargs)

        wrappers[name] = wrapper
    entry = ConfigEntry(
        version=3,
        minor_version=1,
        domain=DOMAIN,
        title="Synthetic BYD TPMS",
        data={
            "username": "synthetic@example.invalid",
            "password": "synthetic-unused",
            "base_url": "https://byd.invalid",
            "country_code": "GB",
            "language": "en",
            "device_profile": DeviceProfile().model_dump(),
        },
        options={"mqtt_enabled": False},
        source="user",
        unique_id="synthetic-byD",
        discovery_keys=MappingProxyType({}),
        subentries_data=None,
    )
    async with aiohttp.ClientSession() as session:
        with patch.object(
            session, "_request", side_effect=blocked_network
        ), patch.object(socket.socket, "sendto", blocked_network), patch(
            "socket.getaddrinfo", blocked_network
        ), patch.object(
            integration, "async_get_clientsession", return_value=session
        ), patch.multiple(
            BydClient, **wrappers
        ), patch.object(
            socket.socket, "connect", blocked_network
        ), patch.object(
            socket.socket, "connect_ex", blocked_network
        ), patch(
            "socket.create_connection", blocked_network
        ):
            try:
                await hass.config_entries.async_add(entry)
                await hass.async_block_till_done()
                assert entry.state is ConfigEntryState.LOADED, entry.reason
                registry = entity_registry.async_get(hass)
                entity_ids = {}
                for vin in VINS:
                    entity_ids[vin] = {}
                    for key in CORNERS:
                        eid = registry.async_get_entity_id(
                            "binary_sensor", DOMAIN, f"{vin}_realtime_{key}"
                        )
                        assert eid is not None, (vin, key)
                        registry.async_update_entity(eid, disabled_by=None)
                        entity_ids[vin][key] = eid
                assert await hass.config_entries.async_reload(entry.entry_id)
                await hass.async_block_till_done()
                assert entry.state is ConfigEntryState.LOADED
                for values in entity_ids.values():
                    assert all(
                        hass.states.get(eid) is not None for eid in values.values()
                    )
                yield hass, entry, cloud, entity_ids
            finally:
                if entry.state is ConfigEntryState.LOADED:
                    await hass.config_entries.async_unload(entry.entry_id)
                await hass.async_stop()


async def refresh(configured, vin, raw):
    hass, entry, cloud, ids = configured
    cloud.payloads[vin] = dict(raw)
    devices = device_registry.async_get(hass)
    device = devices.async_get_device_by_identifier((DOMAIN, vin), entry.entry_id)
    assert device is not None
    before = cloud.reads[vin]
    await hass.services.async_call(
        DOMAIN, "fetch_realtime", {"device_id": device.id}, blocking=True
    )
    await hass.async_block_till_done()
    assert (
        cloud.reads[vin] == before + 1
    ), "The real service must call the synthetic endpoint"
    result = {corner: hass.states.get(eid).state for corner, eid in ids[vin].items()}
    LOGGER.info(
        "Configured HA service observation vin=%s raw=%r states=%r", vin, raw, result
    )
    return result


@pytest.mark.asyncio
async def test_configured_all_wheels_and_other_vehicle(configured):
    hass, _entry, _cloud, ids = configured
    for vin in VINS:
        assert {hass.states.get(eid).state for eid in ids[vin].values()} == {"unknown"}
    fault = {**HEALTHY, ALIASES[0]: 1, ALIASES[1]: 1, ALIASES[3]: 1}
    result = await refresh(configured, VINS[0], fault)
    assert list(result.values()) == ["on", "on", "off", "on"]
    assert {hass.states.get(eid).state for eid in ids[VINS[1]].values()} == {"unknown"}
    result = await refresh(configured, VINS[0], HEALTHY)
    assert list(result.values()) == ["off"] * 4
    assert {hass.states.get(eid).state for eid in ids[VINS[1]].values()} == {"unknown"}
    result = await refresh(configured, VINS[0], {**HEALTHY, ALIASES[2]: 2})
    assert list(result.values()) == ["off", "off", "on", "off"]
    result = await refresh(configured, VINS[0], HEALTHY)
    assert list(result.values()) == ["off"] * 4


@pytest.mark.asyncio
async def test_configured_reload_and_partial(configured):
    hass, entry, cloud, ids = configured
    await refresh(configured, VINS[0], {**HEALTHY, ALIASES[0]: 1})
    # Missing and negative sentinel fields pass through the actual pyBYD state engine.
    result = await refresh(configured, VINS[0], {ALIASES[0]: -1})
    assert result[CORNERS[0]] == "on"
    cloud.payloads[VINS[0]] = {ALIASES[0]: -1}
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ids[VINS[0]][CORNERS[0]]).state == "on"
    result = await refresh(configured, VINS[0], HEALTHY)
    assert result[CORNERS[0]] == "off"
    cloud.payloads[VINS[0]] = dict(HEALTHY)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ids[VINS[0]][CORNERS[0]]).state == "off"


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [True], indirect=True)
async def test_configured_startup_fault_first_healthy(configured):
    hass, _entry, _cloud, ids = configured
    assert hass.states.get(ids[VINS[0]][CORNERS[0]]).state == "on"
    result = await refresh(configured, VINS[0], HEALTHY)
    assert result[CORNERS[0]] == "off"
