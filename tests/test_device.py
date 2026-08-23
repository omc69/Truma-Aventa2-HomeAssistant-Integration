"""Tests for turning inbound frames into state.

A notification can carry more than one message, and each message builds its
parameter map from the state stored so far. Collecting several and applying
only the last therefore loses everything the earlier ones added -- silently,
because the frames themselves decoded perfectly well.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest
from bleak.backends.device import BLEDevice

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.truma_aventa.truma_ble.const import (
    ADDR_INTERFACE,
    CONTROL_MBP,
    MBP_PARAM_DISCOVERY_RESPONSE,
)
from custom_components.truma_aventa.truma_ble.device import TrumaBleDevice
from custom_components.truma_aventa.truma_ble.frames import build, build_mbp

APPLIANCE = 0x0801
OURS = 0x0501


def _answer(source: int, topic: str, parameter: str, value: Any) -> bytes:
    """One parameter-discovery answer, as the appliance sends it."""
    return build_mbp(
        dest=OURS,
        src=source,
        mbp_type=MBP_PARAM_DISCOVERY_RESPONSE,
        body={
            "avail": 1,
            "topics": [
                {
                    "tn": topic,
                    "parameters": [{"tn": topic, "pn": parameter, "v": value}],
                }
            ],
        },
    )


def _last_message(source: int) -> bytes:
    """The sentinel that ends a discovery burst."""
    return build_mbp(
        dest=OURS,
        src=source,
        mbp_type=MBP_PARAM_DISCOVERY_RESPONSE,
        body={"LastMessage": 1},
    )


def _feed(device: TrumaBleDevice, *payloads: bytes) -> None:
    """Deliver notifications the way bleak does, from inside a loop.

    A frame naming a topic the appliance owns schedules a discovery of its
    own, which needs a running loop; without one the whole frame is lost to
    the callback's error handling.
    """

    async def run() -> None:
        for payload in payloads:
            device._on_data(None, bytearray(payload))
        await asyncio.sleep(0)
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    asyncio.run(run())


@pytest.fixture
def device() -> TrumaBleDevice:
    """A device that has never connected, which is all these need."""
    return TrumaBleDevice(
        BLEDevice("FC:DE:C5:F0:A6:35", "Truma iNetX-F0A635", None),
        identity={"UserName": "t", "Muid": "m", "Uuid": "u"},
    )


def test_two_answers_in_one_notification_both_survive(
    device: TrumaBleDevice,
) -> None:
    """The second answer must not overwrite what the first added."""
    _feed(
        device,
        _answer(APPLIANCE, "AirCooling", "Temp", 251)
        + _answer(APPLIANCE, "AmbientLight", "Active", 1),
    )
    raw = device.state.raw
    assert raw["0801/AirCooling.Temp"] == 251
    assert raw["0801/AmbientLight.Active"] == 1


def test_two_devices_finishing_together_are_both_recorded(
    device: TrumaBleDevice,
) -> None:
    """A completion dropped here costs that device every one of its sensors."""
    _feed(device, _last_message(ADDR_INTERFACE) + _last_message(APPLIANCE))
    assert device.state.complete == {"0101", "0801"}


def test_parameters_are_kept_apart_by_device(device: TrumaBleDevice) -> None:
    """Two devices carry the same topic; one must not overwrite the other."""
    _feed(
        device,
        _answer(ADDR_INTERFACE, "RoomClimate", "TgtTemp", 220),
        _answer(APPLIANCE, "RoomClimate", "TgtTemp", 250),
    )
    raw = device.state.raw
    assert raw["0101/RoomClimate.TgtTemp"] == 220
    assert raw["0801/RoomClimate.TgtTemp"] == 250


def test_a_known_parameter_reaches_the_state(device: TrumaBleDevice) -> None:
    """Mapped parameters land on the fields the entities read."""
    _feed(device, _answer(APPLIANCE, "AirCooling", "Temp", 243))
    assert device.state.current_temperature == 243


def test_an_undecodable_body_does_not_stop_the_rest(device: TrumaBleDevice) -> None:
    """One unreadable message must not cost the messages beside it."""
    broken = build(
        dest=OURS,
        src=APPLIANCE,
        control=CONTROL_MBP,
        payload=bytes([MBP_PARAM_DISCOVERY_RESPONSE, 0]) + b"\xbf\x62",
    )
    _feed(device, broken + _answer(APPLIANCE, "AmbientLight", "Active", 1))
    assert device.state.raw["0801/AmbientLight.Active"] == 1
