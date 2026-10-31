"""Real HA core startup after entry setup, with synthetic BYD cloud reads.

The imported configured fixture leaves HA's setup, entry, platforms, coordinators,
models, state engine, entity/device registries, services and sensor state untouched.
Its explicit seams replace cloud authentication/reads and the HTTP session factory;
outbound network is blocked. This adds actual ``hass.async_start`` and started-event
evidence. It does not start a web frontend or validate BYD/vehicle transport.
"""

from __future__ import annotations

import logging

import pytest
import test_configured_tpms as tpms
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState
from test_configured_tpms import (
    ALIASES,
    CORNERS,
    HEALTHY,
    VINS,
    refresh,
)

LOGGER = logging.getLogger("started_tpms")
configured = tpms.configured


@pytest.mark.asyncio
async def test_started_service_warning_clears(configured):
    """A service refresh clears the warning while a real HA core is running."""
    hass, entry, cloud, ids = configured
    started = []
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, started.append)
    await hass.async_start()
    await hass.async_block_till_done()
    assert hass.state is CoreState.running
    assert len(started) == 1
    LOGGER.info("Real Home Assistant startup completed: state=%s", hass.state)
    assert {hass.states.get(eid).state for eid in ids[VINS[0]].values()} == {"unknown"}
    result = await refresh(configured, VINS[0], {**HEALTHY, ALIASES[0]: 1})
    assert list(result.values()) == ["on", "off", "off", "off"]
    result = await refresh(configured, VINS[0], HEALTHY)
    assert list(result.values()) == ["off"] * 4
    assert {hass.states.get(eid).state for eid in ids[VINS[1]].values()} == {"unknown"}
    cloud.payloads[VINS[0]] = dict(HEALTHY)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.state is CoreState.running
    assert hass.states.get(ids[VINS[0]][CORNERS[0]]).state == "off"
