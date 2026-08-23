#!/usr/bin/env python3
"""Decode a PacketLogger text export of Truma BLE traffic.

Walks the whole protocol stack -- UartPackage, MuldexPackage, TruMessageV3,
the MBP sub-header and finally the CBOR payload -- and prints one readable line
per message, so an action log kept during the capture can be matched to the
commands the app actually sent.

    python3 tools/decode_truma_trace.py traces/01-coldstart.txt
    python3 tools/decode_truma_trace.py traces/*.txt --writes-only

Needs cbor2:  pip install cbor2
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field

try:
    import cbor2
except ImportError:  # pragma: no cover - guidance is the point
    print("Bitte zuerst installieren:  pip install cbor2", file=sys.stderr)
    raise SystemExit(1) from None

# --- protocol constants, from docs/truma-inetx-protocol-reference.md --------

CHARACTERISTICS = {
    "fc314001": "CMD",
    "fc314002": "DATA_WRITE",
    "fc314003": "DATA_READ",
    "fc314004": "CMD_ALT",
    "f47b0100": "SERVICE_READ",
    "f47b0101": "SERVICE_WRITE",
}

CONTROL_TYPES = {
    0x01: "DEVICE_REGISTRATION",
    0x02: "DEVICE_DISCOVERY",
    0x03: "MBP",
    0x04: "FILE_MANAGER",
    0x05: "SECURITY",
    0x06: "FIRMWARE_UPDATE",
    0x0A: "NONE",
}

MBP_TYPES = {
    0x00: "INFO",
    0x01: "WRITE",
    0x02: "SUBSCRIBE",
    0x03: "BINARY",
    0x04: "PARAM_DISCOVERY",
    0x82: "SUBSCRIBE_RESP",
    0x84: "PARAM_DISCOVERY_RESP",
}

DEVICES = {
    0x0000: "messageBroker",
    0x0101: "panel",
    0x0102: "panelModel",
    0x0200: "tinMaster",
    0x0201: "tinDevice1",
    0x0202: "tinAventa",
    0x0400: "ciTreiber",
    0x0500: "app0",
    0x0501: "app1",
    0x0600: "bleDevice",
    0x0601: "blePeripheral",
    0xFFFF: "broadcast",
}

#: Topics whose values are tenths of a degree.
TEMPERATURE_PARAMS = {"TgtTemp", "Temp"}

#: TruMessageV3 header length, and the control type carrying topic traffic.
V3_HEADER_LEN = 16
CONTROL_MBP = 0x03

#: Frames carry no checksum, so a resynchronisation can land on ASCII inside a
#: CBOR string and read it as a header. Every candidate header is checked
#: against what the protocol can actually express before it is accepted.
MAX_FRAME_LEN = 4096
MAX_DEVICE_ADDRESS = 0x0FFF

# PacketLogger writes the peer either as a MAC or, once resolved, as the
# advertised name -- so the column is matched loosely rather than as an address.
_LINE = re.compile(
    r"^(?P<stamp>\w+ +\d+ +\d\d:\d\d:\d\d\.\d+)\s+ATT\s+(?P<dir>Send|Receive)\s+"
    r"0x[0-9A-F]{4}\s+(?P<peer>.+?)\s\s+(?P<desc>.*?)\s\s+(?P<hex>(?:[0-9A-F]{2} )+)",
    re.IGNORECASE,
)
_UUID = re.compile(r"(fc3140[0-9a-f]{2}|f47b01[0-9a-f]{2})", re.IGNORECASE)
_HANDLE = re.compile(r"Handle:?\s*0x([0-9A-F]{4})", re.IGNORECASE)
_OPERATION = re.compile(
    r"(Write Request|Write Command|Handle Value Notification|Handle Value Indication)",
    re.IGNORECASE,
)


def detect_channels(path: str) -> dict[int, str]:
    """Work out which handle is which characteristic, from the traffic itself.

    Handles differ between units, and PacketLogger only names the UUID when it
    knows it, so the roles are inferred from behaviour: the command channel
    carries short frames in both directions, the data channels carry the long
    ones, written without a response and notified back.
    """
    written: dict[int, list[int]] = {}
    notified: dict[int, list[int]] = {}
    unacknowledged: set[int] = set()

    with open(path, errors="replace") as handle:
        for line in handle:
            match = _LINE.match(line)
            if not match:
                continue
            operation = _OPERATION.search(match.group("desc"))
            handle_match = _HANDLE.search(match.group("desc"))
            if not operation or not handle_match:
                continue
            attribute = int(handle_match.group(1), 16)
            raw = bytes.fromhex(match.group("hex").replace(" ", ""))
            size = max(len(raw) - 11, 0)
            kind = operation.group(1).lower()
            if kind == "write command":
                unacknowledged.add(attribute)
                written.setdefault(attribute, []).append(size)
            elif kind == "write request":
                written.setdefault(attribute, []).append(size)
            else:
                notified.setdefault(attribute, []).append(size)

    channels: dict[int, str] = {}
    # Short frames both ways is the command channel; the transport FSM only
    # ever exchanges two or three bytes there.
    for attribute, sizes in written.items():
        if attribute in notified and sizes and max(sizes) <= 8:
            channels[attribute] = "CMD"
    for attribute in unacknowledged:
        channels.setdefault(attribute, "DATA_WRITE")
    for attribute, sizes in notified.items():
        if attribute not in channels and sizes and max(sizes) > 8:
            channels[attribute] = "DATA_READ"
    return channels


def _name(table: dict, value: int) -> str:
    return table.get(value, f"0x{value:04X}")


@dataclass
class Reassembler:
    """Collects ATT payload bytes per channel into whole TruMessageV3 frames.

    Over BLE the payload is the V3 message itself -- the UartPackage and
    MuldexPackage layers in the protocol reference belong to the UART
    transport and are absent here. A message larger than the MTU arrives as
    several notifications, so frames are cut by the length the header declares
    rather than by packet boundaries.
    """

    buffers: dict[str, bytearray] = field(default_factory=dict)

    def feed(self, channel: str, data: bytes) -> list[bytes]:
        buf = self.buffers.setdefault(channel, bytearray())
        buf += data
        frames: list[bytes] = []
        while len(buf) >= V3_HEADER_LEN:
            total = _frame_length(buf)
            if total is None:
                # Not a plausible header: drop a byte and try to resynchronise.
                del buf[:1]
                continue
            if len(buf) < total:
                break
            frames.append(bytes(buf[:total]))
            del buf[:total]
        return frames

    def reset(self) -> None:
        """Forget partial frames, e.g. after a reconnect."""
        self.buffers.clear()


def _plausible_address(address: int) -> bool:
    return address == 0xFFFF or address <= MAX_DEVICE_ADDRESS


def _frame_length(buf: bytes) -> int | None:
    """Length of the frame starting at buf[0], or None if this is not a header."""
    if len(buf) < V3_HEADER_LEN:
        return None
    if not _plausible_address(int.from_bytes(buf[0:2], "little")):
        return None
    if not _plausible_address(int.from_bytes(buf[2:4], "little")):
        return None
    if buf[6] not in CONTROL_TYPES:
        return None
    # Packet Size counts the payload plus 9; the frame on the wire is the
    # 16-byte header plus that payload.
    total = V3_HEADER_LEN + int.from_bytes(buf[4:6], "little") - 9
    if not V3_HEADER_LEN <= total <= MAX_FRAME_LEN:
        return None
    return total


def decode_message(frame: bytes) -> dict | None:
    """Split one TruMessageV3 frame into its parts."""
    if len(frame) < V3_HEADER_LEN:
        return None

    result = {
        "dest": int.from_bytes(frame[0:2], "little"),
        "src": int.from_bytes(frame[2:4], "little"),
        "size": int.from_bytes(frame[4:6], "little"),
        "control": frame[6],
        "flags": frame[7],
        "payload": frame[V3_HEADER_LEN:],
    }

    if result["control"] == CONTROL_MBP and len(result["payload"]) >= 2:
        result["mbp_type"] = result["payload"][0]
        result["correlation"] = result["payload"][1]
        try:
            result["cbor"] = cbor2.loads(result["payload"][2:])
        except Exception:
            result["cbor"] = None
    return result


def render(cbor: object) -> str:
    """Render a CBOR payload, expanding temperatures into degrees."""
    if not isinstance(cbor, dict):
        return repr(cbor)
    parts = []
    for key, value in cbor.items():
        if key == "v" and isinstance(value, int) and cbor.get("pn") in TEMPERATURE_PARAMS:
            parts.append(f"{key}={value} ({value / 10:.1f} °C)")
        else:
            parts.append(f"{key}={value!r}")
    return "  ".join(parts)


def process(path: str, writes_only: bool, show_raw: bool) -> None:
    """Decode one trace file."""
    reassemblers: dict[str, Reassembler] = {}
    channels = detect_channels(path)
    print(f"\n=== {path} ===")
    print(
        "Kanäle: "
        + ", ".join(f"0x{h:04X}={n}" for h, n in sorted(channels.items()))
        + "\n"
    )

    with open(path, errors="replace") as handle:
        for line in handle:
            match = _LINE.match(line)
            if not match:
                continue
            desc = match.group("desc")
            uuid_match = _UUID.search(desc)
            handle_match = _HANDLE.search(desc)
            if uuid_match:
                channel = CHARACTERISTICS.get(
                    uuid_match.group(1).lower(), uuid_match.group(1)
                )
            elif handle_match:
                channel = channels.get(int(handle_match.group(1), 16), "")
            else:
                continue
            if not channel or not _OPERATION.search(desc):
                continue
            address = match.group("peer")
            arrow = "-->" if match.group("dir").lower() == "send" else "<--"

            # PacketLogger's trailing hex column is the whole HCI packet; the
            # ATT value starts after the descriptor, which the tail after the
            # opcode gives us. Take the bytes following the handle.
            raw = bytes.fromhex(match.group("hex").replace(" ", ""))
            value = raw[11:] if len(raw) > 11 else b""

            key = f"{address}/{channel}"
            engine = reassemblers.setdefault(key, Reassembler())

            if channel == "CMD":
                if not writes_only:
                    print(f"{match.group('stamp')} {arrow} CMD  {value.hex(' ')}")
                continue

            for frame in engine.feed(channel, value):
                decoded = decode_message(frame)
                if decoded is None:
                    continue
                if writes_only and decoded.get("mbp_type") != 0x01:
                    continue
                control = _name(CONTROL_TYPES, decoded["control"])
                mbp = MBP_TYPES.get(decoded.get("mbp_type", -1), "")
                head = (
                    f"{match.group('stamp')} {arrow} "
                    f"{_name(DEVICES, decoded['src'])}->{_name(DEVICES, decoded['dest'])} "
                    f"{control}{'/' + mbp if mbp else ''}"
                )
                if decoded.get("cbor") is not None:
                    print(f"{head}  {render(decoded['cbor'])}")
                elif show_raw:
                    print(f"{head}  raw={decoded['payload'].hex(' ')}")
                else:
                    print(head)


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", nargs="+", help="PacketLogger text exports")
    parser.add_argument(
        "--writes-only",
        action="store_true",
        help="only commands sent by the app, i.e. what a control action looks like",
    )
    parser.add_argument(
        "--raw", action="store_true", help="also dump payloads that did not decode"
    )
    args = parser.parse_args()
    for path in args.traces:
        process(path, args.writes_only, args.raw)


if __name__ == "__main__":
    main()
