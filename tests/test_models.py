"""Unit tests for the state model."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "truma_aventa"),
)

from truma_ble.const import (
    MODE_COOLING,
    MODE_HEATING_AC,
    MODE_VENTILATING,
)
from truma_ble.models import (
    TrumaState,
    degrees_to_tenths,
    tenths_to_degrees,
)


def test_temperatures_are_tenths_of_a_degree() -> None:
    """Confirmed by captured writes of 160, 260 and 220."""
    assert tenths_to_degrees(220) == 22.0
    assert degrees_to_tenths(22.0) == 220
    assert degrees_to_tenths(16.0) == 160
    assert degrees_to_tenths(30.0) == 300


def test_fan_follows_the_running_mode() -> None:
    """Cooling and heating carry separate fan parameters.

    Reading whichever happens to be set would show a value belonging to a mode
    that is not running.
    """
    state = TrumaState(cooling_fan_mode=1, heating_fan_mode=3, fan_level=2)
    assert state.with_values({"mode": MODE_COOLING}).fan_mode_name == "low"
    assert state.with_values({"mode": MODE_HEATING_AC}).fan_mode_name == "high"
    assert state.with_values({"mode": MODE_VENTILATING}).fan_mode_name == "mid"


def test_mode_names_come_from_the_appliance() -> None:
    """Mode 1 is the automatic mode the app sends when switching on."""
    assert TrumaState(mode=0).mode_name == "off"
    assert TrumaState(mode=1).mode_name == "auto"
    assert TrumaState(mode=2).mode_name == "cooling"
    assert TrumaState(mode=4).mode_name == "heating_ac"
    assert TrumaState(mode=6).mode_name == "dehumidifying"


def test_unknown_values_stay_none() -> None:
    """Nothing is invented before the appliance has reported it."""
    state = TrumaState()
    assert state.mode_name is None
    assert state.fan_mode_name is None
    assert tenths_to_degrees(None) is None
