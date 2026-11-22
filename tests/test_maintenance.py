"""Service history sensors (pyBYD #114)."""

from __future__ import annotations

import asyncio
import datetime
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from pybyd.models.maintenance import MaintenanceHistory, MaintenanceRecord

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.byd_vehicle.coordinator import (  # noqa: E402
    BydDataUpdateCoordinator,
)
from custom_components.byd_vehicle.sensor import (  # noqa: E402
    BydLastServiceDateSensor,
    BydLastServiceMileageSensor,
)


def _history(*records: dict[str, Any]) -> MaintenanceHistory:
    return MaintenanceHistory(
        vin="VIN",
        records=[MaintenanceRecord.model_validate(r) for r in records],
    )


def _entity(cls: type, history: MaintenanceHistory | None) -> Any:
    entity: Any = object.__new__(cls)
    entity.coordinator = SimpleNamespace(maintenance=history)
    return entity


def test_empty_history_is_unknown() -> None:
    history = _history()
    assert _entity(BydLastServiceMileageSensor, history).native_value is None
    date_sensor = _entity(BydLastServiceDateSensor, history)
    assert date_sensor.native_value is None
    assert date_sensor.extra_state_attributes == {
        "shop_name": None,
        "service_count": 0,
    }


def test_latest_record_wins() -> None:
    history = _history(
        {"ro_no": "OLD", "total_mileage": 50210, "last_balance_date": 1760000000000},
        {
            "ro_no": "NEW",
            "total_mileage": 99678,
            "last_balance_date": 1791771512000,
            "shop_name": "BYD Test",
        },
    )
    assert _entity(BydLastServiceMileageSensor, history).native_value == 99678
    date_sensor = _entity(BydLastServiceDateSensor, history)
    assert isinstance(date_sensor.native_value, datetime.date)
    assert date_sensor.extra_state_attributes == {
        "shop_name": "BYD Test",
        "service_count": 2,
    }


def test_before_first_fetch() -> None:
    assert _entity(BydLastServiceMileageSensor, None).native_value is None
    assert _entity(BydLastServiceDateSensor, None).native_value is None


@pytest.mark.parametrize(
    ("probe", "supported"),
    [
        (AsyncMock(return_value=_history()), True),
        # the cloud doesn't offer service history for this car
        (AsyncMock(return_value=None), False),
        # flaky at startup: keep the entities, the poll retries
        (AsyncMock(side_effect=UpdateFailed("1008")), True),
    ],
)
@pytest.mark.asyncio
async def test_maintenance_supported(probe: AsyncMock, supported: bool) -> None:
    coordinator: Any = object.__new__(BydDataUpdateCoordinator)
    coordinator._maintenance_probe = asyncio.Lock()
    coordinator._maintenance_supported = None

    async def _get() -> Any:
        result = await probe()
        coordinator._maintenance_supported = result is not None
        return result

    coordinator.async_get_maintenance = _get
    assert await coordinator.async_maintenance_supported() is supported
