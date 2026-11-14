"""A shorter poll interval brings the pending refresh forward, never back.

Needs Home Assistant and pyBYD installed. Run from the repository root with
``python -m pytest tests``.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.byd_vehicle.coordinator import (
    BydDataUpdateCoordinator,
    BydGpsUpdateCoordinator,
)

COORDINATORS = [BydDataUpdateCoordinator, BydGpsUpdateCoordinator]


class FakeLoop:
    """Records the timers that DataUpdateCoordinator._schedule_refresh sets."""

    def __init__(self, now: float) -> None:
        self.now = now
        self.scheduled: list[float] = []

    def time(self) -> float:
        return self.now

    def call_at(self, when: float, callback: Any, *args: Any) -> SimpleNamespace:
        self.scheduled.append(when)
        return SimpleNamespace(cancel=lambda: None)


def _coordinator(
    cls: type,
    *,
    now: float,
    interval: int = 3600,
    pending: bool = True,
    polling: bool = True,
    data: Any = None,
) -> Any:
    """A coordinator whose last refresh finished at 1000 with ``interval`` set."""
    coordinator: Any = object.__new__(cls)
    coordinator.hass = SimpleNamespace(loop=FakeLoop(1000.0))
    coordinator.name = "test"
    coordinator.config_entry = None
    coordinator._microsecond = 0
    coordinator._retry_after = None
    coordinator._listeners = {}
    coordinator._vin = "TESTVIN0000000001"
    coordinator.data = data
    coordinator._fixed_interval = timedelta(seconds=interval)
    coordinator._polling_enabled = True
    coordinator.update_interval = timedelta(seconds=interval)
    coordinator._unsub_refresh = None
    coordinator._schedule_refresh()
    if not pending:
        coordinator._unsub_refresh = None
    if not polling:
        coordinator._polling_enabled = False
        coordinator.update_interval = None
        coordinator._unsub_refresh = None
    coordinator.hass.loop.scheduled.clear()
    coordinator.hass.loop.now = now
    return coordinator


@pytest.mark.parametrize("cls", COORDINATORS)
def test_shorter_interval_brings_pending_refresh_forward(cls):
    # Last refresh at 1000 with 3600 s, so the next is due at 4600.
    coordinator = _coordinator(cls, now=1100.0)
    coordinator.set_poll_interval(120)
    assert coordinator.update_interval == timedelta(seconds=120)
    assert coordinator.hass.loop.scheduled == [1220]


@pytest.mark.parametrize("cls", COORDINATORS)
def test_shorter_interval_never_pushes_refresh_back(cls):
    # Due at 4600; 1800 s from now (4000) would be 5800, so it stays.
    coordinator = _coordinator(cls, now=4000.0)
    coordinator.set_poll_interval(1800)
    assert coordinator.update_interval == timedelta(seconds=1800)
    assert coordinator.hass.loop.scheduled == []


@pytest.mark.parametrize("cls", COORDINATORS)
@pytest.mark.parametrize("seconds", [3600, 7200])
def test_same_or_longer_interval_leaves_pending_refresh(cls, seconds):
    coordinator = _coordinator(cls, now=1100.0)
    coordinator.set_poll_interval(seconds)
    assert coordinator.update_interval == timedelta(seconds=seconds)
    assert coordinator.hass.loop.scheduled == []


@pytest.mark.parametrize("cls", COORDINATORS)
def test_running_refresh_schedules_the_next_itself(cls):
    coordinator = _coordinator(cls, now=1100.0, pending=False)
    coordinator.set_poll_interval(120)
    assert coordinator.update_interval == timedelta(seconds=120)
    assert coordinator.hass.loop.scheduled == []


@pytest.mark.parametrize("cls", COORDINATORS)
def test_polling_disabled_stays_unscheduled(cls):
    coordinator = _coordinator(cls, now=1100.0, polling=False)
    coordinator.set_poll_interval(120)
    assert coordinator.update_interval is None
    assert coordinator.hass.loop.scheduled == []


def test_ac_slow_charging_brings_forward_to_the_slowed_interval():
    # While AC charging the effective interval is the configured one x4 (#193).
    charging = SimpleNamespace(
        realtime=SimpleNamespace(is_vehicle_on=False, is_charging=True, gl=4000.0),
        charging=None,
    )
    coordinator = _coordinator(
        BydDataUpdateCoordinator, now=1100.0, interval=1800, data=charging
    )
    coordinator.set_poll_interval(60)
    assert coordinator.update_interval == timedelta(seconds=240)
    assert coordinator.hass.loop.scheduled == [1340]


@pytest.mark.parametrize("cls", COORDINATORS)
def test_cut_again_after_a_longer_interval_is_not_pushed_back(cls):
    # 120 brings it forward to 1220; 3600 leaves it; 120 again at 1160 would
    # give 1280, later than the 1220 already pending, so it stays.
    coordinator = _coordinator(cls, now=1100.0)
    coordinator.set_poll_interval(120)
    coordinator.hass.loop.now = 1130.0
    coordinator.set_poll_interval(3600)
    coordinator.hass.loop.now = 1160.0
    coordinator.set_poll_interval(120)
    assert coordinator.hass.loop.scheduled == [1220]


@pytest.mark.parametrize("cls", COORDINATORS)
def test_second_cut_brings_it_forward_again(cls):
    # 240 at 1100 gives 1340; 120 at 1200 gives 1320, sooner, so it moves.
    coordinator = _coordinator(cls, now=1100.0)
    coordinator.set_poll_interval(240)
    coordinator.hass.loop.now = 1200.0
    coordinator.set_poll_interval(120)
    assert coordinator.hass.loop.scheduled == [1340, 1320]


@pytest.mark.parametrize("cls", COORDINATORS)
def test_due_time_follows_a_refresh_scheduled_since(cls):
    # An MQTT push reschedules at 4500 (due 8100); a cut to 3000 at 4550 gives 7550.
    coordinator = _coordinator(cls, now=4500.0)
    coordinator._schedule_refresh()
    coordinator.hass.loop.now = 4550.0
    coordinator.set_poll_interval(3000)
    assert coordinator.hass.loop.scheduled == [8100, 7550]
