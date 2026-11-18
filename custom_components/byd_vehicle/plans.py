"""Climate preconditioning plans: service input and plan summaries.

App 3.6.0 schedules climate through plans (pyBYD#91).  A plan holds up to
three commands (A/C, front seats, steering wheel heat) and runs once,
every day or weekly on some days.  The services build plans from flat
fields; this module maps those fields to pyBYD's plan models and back.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Mapping
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pybyd.models.standby import (
    COMMAND_CLIMATE,
    COMMAND_SEATS,
    COMMAND_STEERING_WHEEL,
    PlanSeats,
    StandbyPlan,
    StandbyPlanCommand,
    StandbySchedule,
)

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
REPEATS = ("off", "single", "every_day", "weekdays", "weekends", "custom")
DURATIONS = (10, 15, 20, 25, 30)
DEFAULT_TEMPERATURE = 21.0
DEFAULT_DURATION = 10

_FIXED_DAYS = {"weekdays": (0, 1, 2, 3, 4), "weekends": (5, 6)}
_SCHEDULE_FIELDS = ("repeat", "start_time", "date", "weekdays")
# service field -> PlanSeats field, capability flag
SEAT_FIELDS: dict[str, tuple[str, str]] = {
    "driver_seat_heat": ("driver_heat", "driver_seat_heat"),
    "driver_seat_ventilation": ("driver_ventilation", "driver_seat_ventilation"),
    "passenger_seat_heat": ("passenger_heat", "passenger_seat_heat"),
    "passenger_seat_ventilation": (
        "passenger_ventilation",
        "passenger_seat_ventilation",
    ),
}
_KNOWN_COMMANDS = (COMMAND_CLIMATE, COMMAND_SEATS, COMMAND_STEERING_WHEEL)
_CLIMATE_KEYS = ("timeSpan", "mainSettingTemp", "copilotSettingTemp")


def plan_zone(plan: StandbyPlan | None) -> datetime.tzinfo:
    """Zone a plan's times are in, HA's zone as a fallback."""
    if plan is not None and plan.time_zone:
        try:
            return ZoneInfo(plan.time_zone)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return dt_util.get_default_time_zone()


def _at(day: datetime.date, hhmm: str, zone: datetime.tzinfo) -> datetime.datetime:
    hour, minute = (int(part) for part in hhmm.split(":"))
    return datetime.datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)


def next_run(plan: StandbyPlan, now: datetime.datetime) -> datetime.datetime | None:
    """The plan's next run after ``now``, ``None`` when it won't run again."""
    schedule = plan.schedule
    if schedule.repeat == "off":
        return None
    if schedule.repeat == "once":
        assert schedule.at is not None
        return schedule.at if schedule.at > now else None
    zone = plan_zone(plan)
    if schedule.repeat == "daily":
        assert schedule.at is not None
        hhmm = schedule.at.astimezone(zone).strftime("%H:%M")
        days: tuple[int, ...] = tuple(range(7))
    else:
        hhmm = schedule.start_time
        days = schedule.weekly_days
    today = now.astimezone(zone).date()
    for offset in range(8):
        day = today + datetime.timedelta(days=offset)
        if day.weekday() in days and (run := _at(day, hhmm, zone)) > now:
            return run
    return None


def _start_time(schedule: StandbySchedule, zone: datetime.tzinfo) -> str | None:
    if schedule.repeat == "weekly":
        return schedule.start_time
    if schedule.at is not None:
        return schedule.at.astimezone(zone).strftime("%H:%M")
    return None


def plan_summary(
    plan: StandbyPlan, *, temp_offset: float, now: datetime.datetime
) -> dict[str, Any]:
    """A plan as flat fields, the same ones the services take."""
    schedule = plan.schedule
    zone = plan_zone(plan)
    summary: dict[str, Any] = {
        "id": plan.id,
        "name": plan.plan_name,
        "preset": plan.preset,
        "default": plan.default_plan == 1,
        "repeat": {"once": "single", "daily": "every_day", "weekly": "custom"}.get(
            schedule.repeat, "off"
        ),
        "start_time": _start_time(schedule, zone),
    }
    if schedule.repeat == "once" and schedule.at is not None:
        summary["date"] = schedule.at.astimezone(zone).date().isoformat()
    if schedule.repeat == "weekly":
        summary["weekdays"] = [DAYS[day] for day in schedule.weekly_days]
    run = next_run(plan, now)
    summary["next_run"] = run.isoformat() if run else None
    climate = plan.climate(temp_offset=temp_offset)
    summary["climate"] = climate is not None
    if climate is not None:
        summary["temperature"] = climate.temperature
        summary["duration"] = climate.duration
    seats = plan.seats
    for field, (seat_field, _) in SEAT_FIELDS.items():
        value = getattr(seats, seat_field) if seats is not None else None
        if value is not None:
            summary[field] = value
    summary["steering_wheel_heat"] = plan.steering_wheel_heat
    return summary


def find_plan(plans: list[StandbyPlan], ref: str) -> StandbyPlan:
    """A plan by id, or by name when exactly one plan has it."""
    ref = str(ref).strip()
    for plan in plans:
        if plan.id == ref:
            return plan
    named = [plan for plan in plans if plan.plan_name == ref]
    if len(named) == 1:
        return named[0]
    if named:
        raise HomeAssistantError(f"More than one climate plan is named {ref!r}")
    raise HomeAssistantError(f"No climate plan with id or name {ref!r}")


def default_plan(plans: list[StandbyPlan]) -> StandbyPlan | None:
    """The default plan, or the first one."""
    return next((plan for plan in plans if plan.default_plan == 1), None) or next(
        iter(plans), None
    )


def _hhmm(value: Any) -> str:
    if isinstance(value, datetime.time):
        return value.strftime("%H:%M")
    parts = str(value).strip().split(":")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except (ValueError, IndexError) as exc:
        raise HomeAssistantError(f"start_time must be HH:MM, got {value!r}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise HomeAssistantError(f"start_time must be HH:MM, got {value!r}")
    return f"{hour:02d}:{minute:02d}"


def _date(value: Any) -> datetime.date:
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise HomeAssistantError(f"date must be YYYY-MM-DD, got {value!r}") from exc


def _next_at(
    hhmm: str, zone: datetime.tzinfo, now: datetime.datetime
) -> datetime.datetime:
    today = now.astimezone(zone).date()
    run = _at(today, hhmm, zone)
    return run if run > now else _at(today + datetime.timedelta(days=1), hhmm, zone)


def schedule_from_call(
    data: Mapping[str, Any],
    *,
    current: StandbySchedule | None,
    zone: datetime.tzinfo,
    now: datetime.datetime,
) -> StandbySchedule | None:
    """Schedule from service fields, ``None`` when none were given.

    Fields left out keep the current schedule's values, so changing only
    ``start_time`` keeps the repeat and days.
    """
    if not any(data.get(field) is not None for field in _SCHEDULE_FIELDS):
        return None
    current = current or StandbySchedule.off()
    current_repeat = {"once": "single", "daily": "every_day", "weekly": "custom"}.get(
        current.repeat, "off"
    )
    repeat = data.get("repeat") or (
        current_repeat if current.repeat != "off" else "single"
    )
    if repeat not in REPEATS:
        raise HomeAssistantError(f"Unknown repeat {repeat!r}")
    if repeat == "off":
        return StandbySchedule.off()

    raw_time = data.get("start_time")
    hhmm = _hhmm(raw_time) if raw_time is not None else _start_time(current, zone)
    if hhmm is None:
        raise HomeAssistantError("start_time is needed to schedule the plan")

    if repeat == "single":
        if data.get("date") is not None:
            at = _at(_date(data["date"]), hhmm, zone)
        else:
            at = _next_at(hhmm, zone, now)
        if at <= now:
            raise HomeAssistantError("Pick a time in the future for the plan")
        return StandbySchedule.once(at)
    if repeat == "every_day":
        return StandbySchedule.daily(_next_at(hhmm, zone, now))
    if repeat in _FIXED_DAYS:
        return StandbySchedule.weekly(hhmm, _FIXED_DAYS[repeat])

    raw_days = data.get("weekdays")
    if raw_days is None:
        days = list(current.weekly_days)
    else:
        if isinstance(raw_days, str):
            raw_days = [raw_days]
        try:
            days = [DAYS.index(str(day).lower()[:3]) for day in raw_days]
        except ValueError as exc:
            raise HomeAssistantError(f"Unknown weekday in {raw_days!r}") from exc
    if not days:
        raise HomeAssistantError("weekdays must be set when repeat is custom")
    return StandbySchedule.weekly(hhmm, days)


def commands_from_call(
    data: Mapping[str, Any],
    *,
    base: StandbyPlan | None,
    temp_offset: float,
    supports: Callable[[str], bool],
) -> list[StandbyPlanCommand]:
    """Plan commands from service fields on top of ``base``'s commands.

    Fields left out keep ``base``'s settings.  Each command is only kept
    when it does something; a plan has to do at least one thing.
    """
    base_commands = list(base.commands) if base is not None else []
    # keep commands we don't model as they are
    commands = [c for c in base_commands if c.command_type not in _KNOWN_COMMANDS]

    climate = _climate_command(data, base, temp_offset)
    if climate is not None:
        commands.insert(0, climate)

    seats = _seats_command(data, base, supports)
    if seats is not None:
        commands.append(seats)

    steering = data.get("steering_wheel_heat")
    existing = base.command(COMMAND_STEERING_WHEEL) if base is not None else None
    if steering is None:
        if existing is not None and base is not None and base.steering_wheel_heat:
            commands.append(existing)
    elif steering:
        if not supports("steering_wheel_heat"):
            raise HomeAssistantError("This car has no steering wheel heat")
        commands.append(StandbyPlanCommand.steering_wheel())

    if not commands:
        raise HomeAssistantError(
            "A climate plan has to turn on the A/C, a seat or the steering wheel heat"
        )
    return commands


def _climate_command(
    data: Mapping[str, Any], base: StandbyPlan | None, temp_offset: float
) -> StandbyPlanCommand | None:
    current = base.climate(temp_offset=temp_offset) if base is not None else None
    existing = base.command(COMMAND_CLIMATE) if base is not None else None
    enabled = data.get("climate")
    touched = data.get("temperature") is not None or data.get("duration") is not None
    if enabled is False or (enabled is None and current is None and not touched):
        return None
    if existing is not None and not touched:
        return existing
    temperature = data.get("temperature")
    if temperature is None:
        temperature = current.temperature if current else DEFAULT_TEMPERATURE
    duration = data.get("duration")
    if duration is None:
        duration = current.duration if current else DEFAULT_DURATION
    try:
        built = StandbyPlanCommand.climate(
            float(temperature), int(duration), temp_offset=temp_offset
        )
    except ValueError as exc:
        raise HomeAssistantError(str(exc)) from exc
    if existing is None:
        return built
    # only change what was asked for, keep eg cycleMode as it is
    changed = {key: built.control_params_map[key] for key in _CLIMATE_KEYS}
    return existing.model_copy(
        update={"control_params_map": {**existing.control_params_map, **changed}}
    )


def _seats_command(
    data: Mapping[str, Any], base: StandbyPlan | None, supports: Callable[[str], bool]
) -> StandbyPlanCommand | None:
    current = base.seats if base is not None else None
    if current is not None and not any(data.get(field) for field in SEAT_FIELDS):
        existing = base.command(COMMAND_SEATS) if base is not None else None
        return existing if current.active else None
    values: dict[str, Any] = {}
    for field, (seat_field, capability) in SEAT_FIELDS.items():
        given = data.get(field)
        if given is not None and not supports(capability):
            raise HomeAssistantError(f"This car has no {field.replace('_', ' ')}")
        if given is not None:
            values[seat_field] = given
        elif current is not None and getattr(current, seat_field) is not None:
            values[seat_field] = getattr(current, seat_field)
        elif supports(capability):
            values[seat_field] = "off"
    seats = PlanSeats(**values)
    return StandbyPlanCommand.seats(seats) if seats.active else None
