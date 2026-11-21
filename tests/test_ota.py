"""Firmware update entity and night auto-upgrade (pyBYD #99)."""

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
from pybyd.models.ota import OtaUpgradeInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.byd_vehicle.coordinator import (  # noqa: E402
    BydDataUpdateCoordinator,
)
from custom_components.byd_vehicle.time import parse_hmm  # noqa: E402
from custom_components.byd_vehicle.update import (  # noqa: E402
    BydFirmwareUpdate,
    release_notes,
)


def _ota(**fields: Any) -> OtaUpgradeInfo:
    raw = {"currentVersion": "1.2.0", "autoUpgradeSwitch": "1"}
    return OtaUpgradeInfo.model_validate({**raw, **fields})


def _entity(ota: OtaUpgradeInfo | None) -> Any:
    entity: Any = object.__new__(BydFirmwareUpdate)
    entity.coordinator = SimpleNamespace(ota=ota)
    return entity


def test_up_to_date() -> None:
    entity = _entity(_ota())
    assert entity.installed_version == "1.2.0"
    assert entity.latest_version == "1.2.0"
    assert entity.in_progress is False


def test_update_offered_and_installing() -> None:
    entity = _entity(_ota(updateVersion="1.3.0", upgradeStatus=3))
    assert entity.latest_version == "1.3.0"
    assert entity.in_progress is True


def test_release_notes() -> None:
    ota = _ota(
        updateVersion="1.3.0",
        functionDescription="Summary",
        functionAddition="New: thing",
        functionOptimization=" ",
    )
    assert release_notes(ota) == "Summary\n\nNew: thing"
    assert release_notes(_ota()) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2:00", datetime.time(2, 0)),
        ("23:30", datetime.time(23, 30)),
        ("", None),
        ("25:00", None),
    ],
)
def test_parse_hmm(raw: str, expected: datetime.time | None) -> None:
    assert parse_hmm(raw) == expected


def _coordinator(ota: OtaUpgradeInfo | None) -> Any:
    coordinator: Any = object.__new__(BydDataUpdateCoordinator)
    coordinator._ota = ota
    coordinator._vin = "VIN"
    coordinator.async_get_ota = AsyncMock()
    coordinator.async_update_listeners = lambda: None
    client = SimpleNamespace(set_ota_auto_upgrade=AsyncMock())

    async def _call(handler: Any, **kwargs: Any) -> Any:
        return await handler(client)

    coordinator._api = SimpleNamespace(async_call=_call)
    coordinator.client = client
    return coordinator


@pytest.mark.asyncio
async def test_set_time_keeps_switch() -> None:
    coordinator = _coordinator(_ota(autoUpgradeTime="2:00"))
    await coordinator.async_set_ota_auto_upgrade(at="3:15")
    coordinator.client.set_ota_auto_upgrade.assert_awaited_once_with(
        "VIN", enabled=True, auto_upgrade_time="3:15"
    )
    coordinator.async_get_ota.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_switch_keeps_time() -> None:
    coordinator = _coordinator(_ota(autoUpgradeTime="4:30"))
    await coordinator.async_set_ota_auto_upgrade(enabled=False)
    coordinator.client.set_ota_auto_upgrade.assert_awaited_once_with(
        "VIN", enabled=False, auto_upgrade_time="4:30"
    )


@pytest.mark.parametrize(
    ("probe", "supported"),
    [
        (AsyncMock(return_value=_ota()), True),
        # the cloud doesn't offer OTA for this car
        (AsyncMock(return_value=None), False),
        # flaky at startup: keep the entities, the poll retries
        (AsyncMock(side_effect=UpdateFailed("1008")), True),
    ],
)
@pytest.mark.asyncio
async def test_ota_supported(probe: AsyncMock, supported: bool) -> None:

    coordinator: Any = object.__new__(BydDataUpdateCoordinator)
    coordinator._ota_probe = asyncio.Lock()
    coordinator._ota_supported = None

    async def _get() -> Any:
        result = await probe()
        coordinator._ota_supported = result is not None
        return result

    coordinator.async_get_ota = _get
    assert await coordinator.async_ota_supported() is supported
