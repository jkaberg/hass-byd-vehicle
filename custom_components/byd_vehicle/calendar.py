"""Calendar of climate preconditioning plans for BYD Vehicle.

App 3.6.0 schedules climate through preconditioning plans: a plan holds
the climate settings, a start time and the weekdays it repeats on.  Each
scheduled plan shows up here as one weekly recurring event.

Editing the whole series changes the plan's time, days, name and run
length; deleting it unschedules the plan (the plan itself stays).
Creating new plans isn't supported yet since the cloud call for it
hasn't been captured (pyBYD#91).
"""

from __future__ import annotations

import datetime
import logging
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.components.calendar.const import (
    EVENT_END,
    EVENT_RRULE,
    EVENT_START,
    EVENT_SUMMARY,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pybyd.models.standby import StandbyPlan, StandbyPlanList
from pybyd.models.vehicle import Vehicle

from .const import DOMAIN
from .coordinator import BydDataUpdateCoordinator
from .entity import BydVehicleEntity

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = datetime.timedelta(minutes=30)

_BYDAY = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
# OPENAIR timeSpan code -> run length in minutes
_TIME_SPAN_MINUTES = {1: 10, 2: 15, 3: 20, 4: 25, 5: 30}
_DEFAULT_MINUTES = 10


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one plan calendar per vehicle that supports plans."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, BydDataUpdateCoordinator] = data["coordinators"]

    entities: list[CalendarEntity] = []
    for vin, coordinator in coordinators.items():
        try:
            plans = await coordinator.async_get_standby_plans()
        except UpdateFailed as exc:
            # transient, keep the entity and let it retry on its own poll
            _LOGGER.debug("Plan fetch failed at setup: vin=%s, error=%s", vin[-6:], exc)
            plans = StandbyPlanList(vin=vin)
        if plans is None:
            # guest accounts get 1001 on the plan list
            _LOGGER.debug("Climate plans not available: vin=%s", vin[-6:])
            continue
        entities.append(BydPlanCalendar(coordinator, vin, coordinator.vehicle, plans))

    async_add_entities(entities)


def plan_minutes(plan: StandbyPlan) -> int:
    """Run length of a plan's climate command in minutes."""
    for command in plan.commands:
        if command.command_type == "OPENAIR":
            return _TIME_SPAN_MINUTES.get(
                command.control_params_map.get("timeSpan"), _DEFAULT_MINUTES
            )
    return _DEFAULT_MINUTES


def plan_zone(plan: StandbyPlan) -> datetime.tzinfo:
    """Time zone the plan's start time is in, HA's zone as a fallback."""
    if plan.time_zone:
        try:
            return ZoneInfo(plan.time_zone)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return dt_util.get_default_time_zone()


def plan_rrule(plan: StandbyPlan) -> str:
    """Weekly RRULE for the plan's days (0 = Monday)."""
    return "FREQ=WEEKLY;BYDAY=" + ",".join(_BYDAY[day] for day in plan.weekly_days)


def plan_occurrences(
    plan: StandbyPlan, start: datetime.datetime, end: datetime.datetime
) -> list[CalendarEvent]:
    """Expand a scheduled plan into the events overlapping ``start``-``end``."""
    if not plan.scheduled:
        return []
    zone = plan_zone(plan)
    hour, minute = (int(part) for part in plan.start_time.split(":"))
    length = datetime.timedelta(minutes=plan_minutes(plan))
    rrule = plan_rrule(plan)
    events: list[CalendarEvent] = []
    day = (start - length).astimezone(zone).date()
    last = end.astimezone(zone).date()
    while day <= last:
        if day.weekday() in plan.weekly_days:
            begin = datetime.datetime(
                day.year, day.month, day.day, hour, minute, tzinfo=zone
            )
            finish = begin + length
            if finish > start and begin < end:
                events.append(
                    CalendarEvent(
                        start=begin,
                        end=finish,
                        summary=plan.plan_name,
                        uid=plan.id,
                        rrule=rrule,
                        recurrence_id=begin.strftime("%Y%m%dT%H%M%S"),
                    )
                )
        day += datetime.timedelta(days=1)
    return events


def parse_weekly_rrule(rrule: str | None) -> list[int]:
    """Weekdays (0 = Monday) from a weekly RRULE, or raise if plans can't hold it."""
    if not rrule:
        raise HomeAssistantError(
            "Climate plans repeat weekly; set the event to repeat weekly"
        )
    parts = dict(
        part.split("=", 1)
        for part in rrule.removeprefix("RRULE:").split(";")
        if "=" in part
    )
    if parts.get("FREQ") != "WEEKLY":
        raise HomeAssistantError("Climate plans can only repeat weekly")
    if parts.get("INTERVAL", "1") != "1":
        raise HomeAssistantError("Climate plans can't repeat every other week")
    if "COUNT" in parts or "UNTIL" in parts:
        raise HomeAssistantError(
            "Climate plans repeat until changed; remove the end of the repeat"
        )
    days = parts.get("BYDAY", "")
    try:
        weekdays = sorted({_BYDAY.index(day[-2:]) for day in days.split(",") if day})
    except ValueError as exc:
        raise HomeAssistantError(f"Unsupported repeat days: {days}") from exc
    if not weekdays:
        raise HomeAssistantError("Pick at least one weekday for the plan")
    return weekdays


def time_span_for(minutes: float) -> int:
    """OPENAIR timeSpan code for a run length, clamped to 10-30 minutes."""
    clamped = min(max(minutes, 10), 30)
    return int(round((clamped - 10) / 5)) + 1


def apply_event(
    plan: StandbyPlan, event: dict[str, Any]
) -> tuple[StandbyPlan, str, list[int]]:
    """Map an edited calendar event onto the plan.

    Returns the updated plan plus the ``HH:MM`` start and weekdays to save.
    The run length is clamped to the 10-30 minutes the car supports.
    """
    start = event[EVENT_START]
    end = event[EVENT_END]
    if not isinstance(start, datetime.datetime) or not isinstance(
        end, datetime.datetime
    ):
        raise HomeAssistantError(
            "Climate plans need a start time, not an all-day event"
        )
    weekdays = parse_weekly_rrule(event.get(EVENT_RRULE))
    local_start = start.astimezone(plan_zone(plan)) if start.tzinfo else start
    span = time_span_for((end - start).total_seconds() / 60)
    commands = [
        command.model_copy(
            update={
                "control_params_map": {**command.control_params_map, "timeSpan": span}
            }
        )
        if command.command_type == "OPENAIR"
        else command
        for command in plan.commands
    ]
    updated = plan.model_copy(
        update={
            "plan_name": event.get(EVENT_SUMMARY) or plan.plan_name,
            "commands": commands,
        }
    )
    return updated, local_start.strftime("%H:%M"), weekdays


class BydPlanCalendar(BydVehicleEntity, CalendarEntity):
    """Climate preconditioning plans as a calendar."""

    _attr_has_entity_name = True
    _attr_translation_key = "climate_plans"
    _attr_icon = "mdi:calendar-clock"
    _attr_supported_features = (
        CalendarEntityFeature.UPDATE_EVENT | CalendarEntityFeature.DELETE_EVENT
    )

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
        plans: StandbyPlanList,
    ) -> None:
        self._vin = vin
        self._vehicle = vehicle
        super().__init__(coordinator)
        self._attr_unique_id = f"{vin}_calendar_climate_plans"
        self._plans = plans

    @property
    def should_poll(self) -> bool:
        """Plans aren't part of the telemetry snapshot, so poll them."""
        return True

    async def async_update(self) -> None:
        """Refresh the plans."""
        try:
            plans = await self.coordinator.async_get_standby_plans()
        except UpdateFailed as exc:
            _LOGGER.debug("Plan refresh failed: vin=%s, error=%s", self._vin[-6:], exc)
            return
        if plans is not None:
            self._plans = plans

    @property
    def event(self) -> CalendarEvent | None:
        """The current or next plan run."""
        now = dt_util.now()
        upcoming = [
            event
            for plan in self._plans.plans
            for event in plan_occurrences(plan, now, now + datetime.timedelta(days=8))
        ]
        return min(upcoming, key=lambda event: event.start_datetime_local, default=None)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Plan runs within the range."""
        events = [
            event
            for plan in self._plans.plans
            for event in plan_occurrences(plan, start_date, end_date)
        ]
        return sorted(events, key=lambda event: event.start_datetime_local)

    def _plan(self, uid: str) -> StandbyPlan:
        for plan in self._plans.plans:
            if plan.id == uid:
                return plan
        raise HomeAssistantError(f"No climate plan with id {uid}")

    @staticmethod
    def _whole_series_only(
        recurrence_id: str | None, recurrence_range: str | None
    ) -> None:
        # a plan has one time and one set of days, so single runs can't differ
        if recurrence_id and recurrence_range != "THISANDFUTURE":
            raise HomeAssistantError(
                "Climate plans can only be changed for all events in the series"
            )

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Change a plan's time, days, name and run length."""
        self._whole_series_only(recurrence_id, recurrence_range)
        plan, start_time, weekdays = apply_event(self._plan(uid), event)
        self._plans = await self.coordinator.async_save_standby_plan(
            plan, start_time=start_time, weekly_days=weekdays
        )
        self.async_write_ha_state()

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Unschedule a plan; the plan and its settings are kept."""
        self._whole_series_only(recurrence_id, recurrence_range)
        self._plans = await self.coordinator.async_save_standby_plan(
            self._plan(uid), start_time="", weekly_days=[]
        )
        self.async_write_ha_state()
