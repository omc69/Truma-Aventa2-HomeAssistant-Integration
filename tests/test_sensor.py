"""Tests for the parameter sensors.

These exercise the Home Assistant layer rather than the protocol, because that
is where the last two releases broke: a name used but never imported, and an
``_attr_`` read back on entities that never set it. Neither is visible to a
linter and neither showed up in a protocol test, but both raise the moment an
entity writes its state -- which is all it takes to reproduce them here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.truma_aventa.const import DOMAIN
from custom_components.truma_aventa.sensor import (
    TrumaParameterSensor,
    _group_addresses,
    _parameters,
    _readable,
)
from custom_components.truma_aventa.truma_ble.models import TrumaState

#: Two addresses of one interface plus the air conditioning, as captured.
RAW: dict[str, Any] = {
    "0101/Identify.UniqueID": "0a69818a.device.id.ii.inetx",
    "0101/Identify.Name": "iNet X Interface AC",
    "0101/Identify.SerialNr": "IIIRTEU-A-37071464",
    "0101/Identify.SwMaj": 3,
    "0101/Identify.SwMin": 5,
    "0101/Temperature.Internal": 249,
    "0200/Identify.UniqueID": "0a69818a.device.id.ii.inetx",
    "0200/RoomClimate.TgtTemp": 220,
    "0801/Identify.UniqueID": "aventa.device.id",
    "0801/Identify.Name": "Aventa comfort 2. G",
    "0801/AirCooling.Temp": 251,
    "0801/System.Plugged": 1,
    "0801/TimerConfig.Timer1": {"id": 0, "name": "DefaultTimer"},
    "0801/MobileIdentity.Muid": "7D6EBC83-D706-477E-A5B9-EC145D8C7518",
    # A bookkeeping endpoint: answers on the bus, names nothing, and reports
    # only its own registration state.
    "0601/DeviceManagement.RegCompleted": 1,
}

COMPLETE = frozenset({"0101", "0200", "0801", "0601"})


class _Coordinator:
    """The little of a coordinator an entity touches before it is added."""

    def __init__(self, state: TrumaState) -> None:
        self.data = state
        self.key = "Truma iNetX-F0A635"
        self.available = True
        self.last_update_success = True

    def async_add_listener(self, *_: Any) -> Any:
        return lambda: None


@pytest.fixture
def coordinator() -> _Coordinator:
    """A coordinator holding the captured parameters."""
    return _Coordinator(TrumaState(raw=dict(RAW), complete=COMPLETE))


def _sensor(coordinator: _Coordinator, parameter: str) -> TrumaParameterSensor:
    """Build the sensor the platform would build for one parameter."""
    for identity, addresses in _group_addresses(
        coordinator.data.raw, coordinator.data.complete
    ).items():
        if parameter in _parameters(coordinator.data.raw, addresses):
            return TrumaParameterSensor(coordinator, identity, addresses, parameter)
    raise AssertionError(f"no device reports {parameter}")


# --- the regressions -------------------------------------------------------


def test_a_plain_parameter_can_report_its_state(coordinator: _Coordinator) -> None:
    """Reading a state must not raise for a parameter with no device class."""
    assert _sensor(coordinator, "System.Plugged").native_value == 1


def test_every_parameter_can_report_its_state(coordinator: _Coordinator) -> None:
    """The fault only showed on some parameters, so check all of them."""
    for identity, addresses in _group_addresses(
        coordinator.data.raw, coordinator.data.complete
    ).items():
        for parameter in _parameters(coordinator.data.raw, addresses):
            sensor = TrumaParameterSensor(coordinator, identity, addresses, parameter)
            sensor.native_value  # noqa: B018 -- raising is the failure


# --- values ----------------------------------------------------------------


def test_temperatures_are_converted_from_tenths(coordinator: _Coordinator) -> None:
    """The appliance reports 249 for 24.9 degrees."""
    assert _sensor(coordinator, "Temperature.Internal").native_value == 24.9
    assert _sensor(coordinator, "AirCooling.Temp").native_value == 25.1


def test_structured_values_become_readable(coordinator: _Coordinator) -> None:
    """A state can hold a string; a timer arrives as a map."""
    value = _sensor(coordinator, "TimerConfig.Timer1").native_value
    assert isinstance(value, str)
    assert "DefaultTimer" in value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (5, 5),
        (1.5, 1.5),
        (b"\x01\xff", "01ff"),
        ([], "[]"),
    ],
)
def test_readable_renders(value: Any, expected: Any) -> None:
    """Whatever CBOR produced has to fit in a state."""
    assert _readable(value) == expected


def test_a_long_value_is_cut_to_what_a_state_holds() -> None:
    """States are limited to 255 characters."""
    assert len(_readable(["x" * 400])) == 255


# --- grouping --------------------------------------------------------------


def test_addresses_of_one_device_are_folded(coordinator: _Coordinator) -> None:
    """The interface answers on several addresses under one identity."""
    groups = _group_addresses(coordinator.data.raw, coordinator.data.complete)
    assert groups["0a69818a.device.id.ii.inetx"] == ["0101", "0200"]
    # The interface, the air conditioning, and one bookkeeping endpoint.
    assert len(groups) == 3


def test_a_folded_device_merges_what_its_addresses_report(
    coordinator: _Coordinator,
) -> None:
    """A parameter reported by either address belongs to the one device."""
    found = _parameters(coordinator.data.raw, ["0101", "0200"])
    assert "Temperature.Internal" in found
    assert "RoomClimate.TgtTemp" in found


def test_a_device_still_reporting_is_left_alone(coordinator: _Coordinator) -> None:
    """Grouping before a device names itself files it twice."""
    raw = dict(coordinator.data.raw)
    raw["0904/AirCooling.Mode"] = 1
    assert "0904" not in str(_group_addresses(raw, COMPLETE))


def test_our_own_identity_is_not_published(coordinator: _Coordinator) -> None:
    """MobileIdentity is what we told the appliance about ourselves."""
    found = _parameters(coordinator.data.raw, ["0801"])
    assert not any(parameter.startswith("MobileIdentity") for parameter in found)


# --- which bus addresses deserve a device ----------------------------------


def test_an_address_that_names_itself_gets_its_own_device(
    coordinator: _Coordinator,
) -> None:
    """The air conditioning is a device in its own right."""
    info = _sensor(coordinator, "AirCooling.Temp").device_info
    assert info["name"] == "Aventa comfort 2. G"


def test_a_bookkeeping_endpoint_does_not(coordinator: _Coordinator) -> None:
    """The bus answers on more addresses than the system has hardware.

    Registration slots, the BLE chip and the Bluetooth record each report a
    handful of their own parameters. A device apiece buries the two that
    matter in a list of nine, so their parameters go to the appliance.
    """
    sensor = _sensor(coordinator, "DeviceManagement.RegCompleted")
    assert sensor.device_info["identifiers"] == {(DOMAIN, coordinator.key)}
    assert sensor.name.startswith("0x0601 ")
