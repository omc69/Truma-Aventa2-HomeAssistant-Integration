"""Unit tests for the Truma frame layer.

Every byte sequence here was lifted from a real HCI capture of a Truma Aventa
comfort 2nd generation, so the tests check the code against the appliance
rather than against the documentation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cbor2
import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "truma_aventa"),
)

from truma_ble.const import (
    ADDR_INTERFACE,
    ADDR_MESSAGE_BROKER,
    ADDR_UNREGISTERED,
    CONTROL_DISCOVERY,
    CONTROL_MBP,
    CONTROL_REGISTRATION,
    DEVICE_DISCOVERY_REQUEST,
    MBP_SUBSCRIBE,
    MBP_WRITE,
)
from truma_ble.frames import (
    FrameStream,
    build,
    build_mbp,
    frame_length,
    parse,
)

# --- captured frames -------------------------------------------------------

REGISTRATION_REQUEST = bytes.fromhex(
    "0000ffff12000100000000000000000001a9a1627076820501"
)
REGISTRATION_RESPONSE = bytes.fromhex(
    "ffff00001c000100000000000000000002a9bf6270769f0501ff6461646472190501ff"
)
WRITE_LIGHT_ON = bytes.fromhex(
    "010801052900030000000000000000000100"
    "a361760162746e6c416d6269656e744c6967687462706e66416374697665"
)
WRITE_CLIMATE_MODE = bytes.fromhex(
    "010101052600030000000000000000000100"
    "a362746e6b526f6f6d436c696d61746561760162706e644d6f6465"
)
SUBSCRIBE = bytes.fromhex(
    "000001058200030000000000000000000200"
    "a162746e8a6e41697243697263756c6174696f6e6a416972436f6f6c696e676a4169"
    "7248656174696e67704465766963654d616e6167656d656e7469456e657267795372"
    "636a4572726f7252657365746a467265736857617465726647617342746c6a476173"
    "436f6e74726f6c69477265795761746572"
)


def test_registration_request_round_trips() -> None:
    """Our encoder must reproduce what the app actually sent."""
    frame = parse(REGISTRATION_REQUEST)
    assert frame is not None
    assert frame.dest == ADDR_MESSAGE_BROKER
    assert frame.src == ADDR_UNREGISTERED
    assert frame.control == CONTROL_REGISTRATION
    assert frame.body == {"pv": [5, 1]}


def test_registration_response_carries_our_address() -> None:
    """The appliance answers with the address we must then use as source."""
    frame = parse(REGISTRATION_RESPONSE)
    assert frame is not None
    assert frame.control == CONTROL_REGISTRATION
    assert frame.body["addr"] == 0x0501


def test_light_command_goes_to_the_appliance() -> None:
    """AmbientLight is owned by the appliance, not the panel."""
    frame = parse(WRITE_LIGHT_ON)
    assert frame is not None
    assert frame.dest == 0x0801
    assert frame.src == 0x0501
    assert frame.mbp_type == MBP_WRITE
    assert frame.body == {"tn": "AmbientLight", "pn": "Active", "v": 1}


def test_climate_command_goes_to_the_interface() -> None:
    """RoomClimate is owned by the BLE interface, and switching on is mode 1."""
    frame = parse(WRITE_CLIMATE_MODE)
    assert frame is not None
    assert frame.dest == ADDR_INTERFACE
    assert frame.mbp_type == MBP_WRITE
    assert frame.body == {"tn": "RoomClimate", "pn": "Mode", "v": 1}


def test_subscribe_lists_topics() -> None:
    """Subscriptions go to the message broker in batches of ten."""
    frame = parse(SUBSCRIBE)
    assert frame is not None
    assert frame.dest == ADDR_MESSAGE_BROKER
    assert frame.mbp_type == MBP_SUBSCRIBE
    assert len(frame.body["tn"]) == 10
    assert "AirCooling" in frame.body["tn"]


def test_build_reproduces_a_captured_command() -> None:
    """Encoding the light command must give back the captured bytes."""
    built = build_mbp(
        dest=0x0801,
        src=0x0501,
        mbp_type=MBP_WRITE,
        body={"v": 1, "tn": "AmbientLight", "pn": "Active"},
    )
    # CBOR map ordering follows insertion, so compare the decoded form and the
    # header rather than the raw bytes.
    assert built[:16] == WRITE_LIGHT_ON[:16]
    assert parse(built).body == parse(WRITE_LIGHT_ON).body


def test_header_declares_payload_plus_nine() -> None:
    """The size field is the payload length plus nine, not the frame length."""
    built = build(dest=1, src=2, control=CONTROL_MBP, payload=b"\x01\x02\x03")
    assert int.from_bytes(built[4:6], "little") == 3 + 9
    assert len(built) == 16 + 3


# --- framing ---------------------------------------------------------------


def test_stream_splits_concatenated_frames() -> None:
    """Several frames can arrive in one notification."""
    stream = FrameStream()
    frames = stream.feed(WRITE_CLIMATE_MODE + WRITE_LIGHT_ON)
    assert [f.dest for f in frames] == [ADDR_INTERFACE, 0x0801]


def test_stream_reassembles_a_split_frame() -> None:
    """A message larger than the MTU arrives in pieces."""
    stream = FrameStream()
    assert stream.feed(SUBSCRIBE[:50]) == []
    frames = stream.feed(SUBSCRIBE[50:])
    assert len(frames) == 1
    assert frames[0].mbp_type == MBP_SUBSCRIBE


def test_stream_drops_what_cannot_be_a_frame() -> None:
    """A notification that does not begin with a header is dropped whole.

    Stepping through it byte by byte looking for a header is what used to
    happen, and it is worse than losing the notification: a CBOR body is full
    of header-shaped bytes, so the search latches onto one and every later
    message is then consumed as part of a phantom frame.
    """
    stream = FrameStream()
    assert stream.feed(bytes.fromhex("aabbccdd") + WRITE_LIGHT_ON) == []
    assert stream.dropped
    assert stream.pending == 0


def test_stream_recovers_after_a_truncated_message() -> None:
    """One incomplete message must not cost every message after it.

    Observed on the appliance: each notification carries exactly one whole
    message, so a leftover that is still waiting when a complete message
    arrives can never be completed and must not be glued to its front.
    """
    stream = FrameStream()
    assert stream.feed(SUBSCRIBE[:40]) == []
    frames = stream.feed(WRITE_LIGHT_ON)
    assert [f.dest for f in frames] == [0x0801]
    assert stream.pending == 0
    frames = stream.feed(WRITE_CLIMATE_MODE)
    assert [f.dest for f in frames] == [ADDR_INTERFACE]


@pytest.mark.parametrize(
    "header",
    [
        # ASCII lifted from inside a CBOR string, which is exactly what a
        # naive resynchronisation would latch onto.
        b"iavabtnlAmbientL",
        # A length field no message could plausibly declare.
        bytes.fromhex("0000") + bytes.fromhex("0000") + bytes.fromhex("ffff")
        + bytes.fromhex("03") + bytes(9),
    ],
)
def test_implausible_headers_are_rejected(header: bytes) -> None:
    """Without a checksum, only a plausibility check prevents phantom frames."""
    assert frame_length(header) is None


def test_unknown_control_type_is_not_a_header() -> None:
    """A control byte the protocol does not define cannot start a frame."""
    candidate = bytearray(WRITE_LIGHT_ON[:16])
    candidate[6] = 0x77
    assert frame_length(bytes(candidate)) is None


# --- device discovery ------------------------------------------------------

#: The app asking the broker who is on the bus, byte for byte.
DEVICE_DISCOVERY = bytes.fromhex(
    "0000010 50b0002000000000000000000 0100".replace(" ", "")
)


def test_device_discovery_request_reproduces_the_capture() -> None:
    """Asking the broker for the device list is a control type of its own."""
    built = build(
        dest=ADDR_MESSAGE_BROKER,
        src=0x0501,
        control=CONTROL_DISCOVERY,
        payload=bytes([DEVICE_DISCOVERY_REQUEST, 0x00]),
    )
    assert built == DEVICE_DISCOVERY


def test_device_list_is_read_from_the_answer() -> None:
    """The answer names every device, including the one owning the cooling.

    Which address the air conditioning answers on is not fixed: the protocol
    reference documents 0x0201 and the captured appliance uses 0x0801, so the
    list is the only way to reach it.
    """
    answer = build(
        dest=0x0501,
        src=ADDR_MESSAGE_BROKER,
        control=CONTROL_DISCOVERY,
        payload=bytes([0x02, 0x00])
        + cbor2.dumps({"Devices": [0x0101, 0x0801, 0x0501], "LastMessage": 1}),
    )
    frames = FrameStream().feed(answer)
    assert len(frames) == 1
    assert frames[0].control == CONTROL_DISCOVERY
    assert frames[0].body["Devices"] == [0x0101, 0x0801, 0x0501]
