"""Tests for the climate entity."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from homeassistant.components.climate import HVACAction, HVACMode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.truma_aventa.climate import TrumaClimate
from custom_components.truma_aventa.truma_ble.const import (
    MODE_COOLING,
    MODE_OFF,
    MODE_VENTILATING,
)
from custom_components.truma_aventa.truma_ble.models import TrumaState


class _Device:
    address = "FC:DE:C5:F0:A6:35"
    name = "Truma iNetX-F0A635"


class _Coordinator:
    """The little of a coordinator an entity touches before it is added."""

    def __init__(self, state: TrumaState) -> None:
        self.data = state
        self.device = _Device()
        self.key = "Truma iNetX-F0A635"
        self.available = True
        self.last_update_success = True

    def async_add_listener(self, *_: Any) -> Any:
        return lambda: None


def _climate(**state: Any) -> TrumaClimate:
    """A climate entity over the given state."""
    return TrumaClimate(_Coordinator(TrumaState(**state)))


def test_nothing_known_yet_reports_nothing() -> None:
    """Before the appliance has answered there is no action to report."""
    assert _climate().hvac_action is None


def test_switched_off_is_off() -> None:
    """Off is a state of its own, not idleness."""
    assert _climate(mode=MODE_OFF).hvac_action is HVACAction.OFF


def test_cooling_while_the_compressor_runs() -> None:
    """The mode says what was asked for; Active says what is happening."""
    entity = _climate(mode=MODE_COOLING, cooling_active=1)
    assert entity.hvac_mode is HVACMode.COOL
    assert entity.hvac_action is HVACAction.COOLING


def test_at_temperature_the_appliance_is_idle() -> None:
    """Cooling requested, compressor off: the target has been reached."""
    entity = _climate(mode=MODE_COOLING, cooling_active=0)
    assert entity.hvac_mode is HVACMode.COOL
    assert entity.hvac_action is HVACAction.IDLE


@pytest.mark.parametrize(
    ("running", "expected"),
    [
        ("heating_active", HVACAction.HEATING),
        ("dehumid_active", HVACAction.DRYING),
        ("circulation_active", HVACAction.FAN),
    ],
)
def test_each_function_reports_its_own_action(running: str, expected: Any) -> None:
    """Every function says separately whether it is running."""
    assert _climate(mode=MODE_VENTILATING, **{running: 1}).hvac_action is expected


def test_temperatures_come_from_tenths() -> None:
    """The appliance counts in tenths of a degree."""
    entity = _climate(current_temperature=251, target_temperature=220)
    assert entity.current_temperature == 25.1
    assert entity.target_temperature == 22.0
