"""The open windows button needs pyBYD's full gate, not just latest_config."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.byd_vehicle import button  # noqa: E402
from custom_components.byd_vehicle.const import DOMAIN  # noqa: E402


class _Coordinator:
    def __init__(self, open_available: bool) -> None:
        self.vehicle = SimpleNamespace(model_name="ATTO 3", brand_name="BYD")
        self.car = SimpleNamespace(
            windows=SimpleNamespace(open_available=open_available)
        )

    def capability_available(self, key: str) -> bool:
        # latest_config says yes, as it does on an ATTO 3 EVO (#20)
        return key == "open_windows"


async def _keys(monkeypatch: pytest.MonkeyPatch, open_available: bool) -> list[str]:
    for name in ("BydForcePollButton", "BydStartChargingButton", "BydFetchEnergyButton"):
        monkeypatch.setattr(button, name, lambda *args: None)
    monkeypatch.setattr(
        button, "BydButton", lambda coordinator, vin, vehicle, desc: desc.key
    )
    entry = SimpleNamespace(entry_id="e")
    hass: Any = SimpleNamespace(
        data={DOMAIN: {"e": {"coordinators": {"VIN": _Coordinator(open_available)}}}}
    )
    added: list[Any] = []
    await button.async_setup_entry(hass, entry, added.extend)  # type: ignore[arg-type]
    return [key for key in added if isinstance(key, str)]


@pytest.mark.asyncio
async def test_open_windows_needs_learn_info(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await _keys(monkeypatch, open_available=False) == []


@pytest.mark.asyncio
async def test_open_windows_when_gate_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await _keys(monkeypatch, open_available=True) == ["open_windows"]
