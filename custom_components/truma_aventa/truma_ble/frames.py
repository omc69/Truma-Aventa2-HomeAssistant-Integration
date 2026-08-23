"""Encoding and decoding of TruMessageV3 frames.

Over BLE an ATT payload starts directly with the 16-byte V3 header -- the
UartPackage and MuldexPackage layers described in the protocol reference belong
to the UART transport. A message longer than the MTU arrives split across
several notifications, so frames are cut by the length the header declares
rather than by packet boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cbor2

from .const import (
    CONTROL_MBP,
    CONTROL_TYPES,
    MAX_DEVICE_ADDRESS,
    V3_HEADER_LEN,
    V3_SIZE_OVERHEAD,
)

#: Nothing legitimate approaches this; it only bounds a bad length field.
MAX_FRAME_LEN = 4096


@dataclass(frozen=True, slots=True)
class Frame:
    """One decoded TruMessageV3 message."""

    dest: int
    src: int
    control: int
    payload: bytes

    @property
    def mbp_type(self) -> int | None:
        """Sub-protocol message type, for topic traffic."""
        if self.control != CONTROL_MBP or len(self.payload) < 2:
            return None
        return self.payload[0]

    @property
    def correlation(self) -> int | None:
        """Correlation id echoed between request and response."""
        if len(self.payload) < 2:
            return None
        return self.payload[1]

    @property
    def body(self) -> Any:
        """CBOR body, or None when there is none or it does not parse."""
        if len(self.payload) < 3:
            return None
        try:
            return cbor2.loads(self.payload[2:])
        except Exception:
            return None


def build(
    *,
    dest: int,
    src: int,
    control: int,
    payload: bytes,
) -> bytes:
    """Wrap a payload in a V3 header."""
    header = bytearray(V3_HEADER_LEN)
    header[0:2] = dest.to_bytes(2, "little")
    header[2:4] = src.to_bytes(2, "little")
    header[4:6] = (len(payload) + V3_SIZE_OVERHEAD).to_bytes(2, "little")
    header[6] = control
    # Bytes 7-15 are the segmentation header; zero means a single unsegmented
    # message, which is all we ever send.
    return bytes(header) + payload


def build_mbp(
    *,
    dest: int,
    src: int,
    mbp_type: int,
    correlation: int = 0,
    body: Any = None,
) -> bytes:
    """Build a message-broker frame with an optional CBOR body."""
    payload = bytes([mbp_type, correlation])
    if body is not None:
        payload += cbor2.dumps(body)
    return build(dest=dest, src=src, control=CONTROL_MBP, payload=payload)


def _plausible_address(address: int) -> bool:
    return address == 0xFFFF or address <= MAX_DEVICE_ADDRESS


def frame_length(buf: bytes) -> int | None:
    """Total length of the frame starting at buf[0], or None if not a header.

    Frames carry no checksum, so a resynchronisation can land inside a CBOR
    string and read ASCII as a header. Every candidate is checked against what
    the protocol can actually express before it is accepted.
    """
    if len(buf) < V3_HEADER_LEN:
        return None
    if not _plausible_address(int.from_bytes(buf[0:2], "little")):
        return None
    if not _plausible_address(int.from_bytes(buf[2:4], "little")):
        return None
    if buf[6] not in CONTROL_TYPES:
        return None
    total = V3_HEADER_LEN + int.from_bytes(buf[4:6], "little") - V3_SIZE_OVERHEAD
    if not V3_HEADER_LEN <= total <= MAX_FRAME_LEN:
        return None
    return total


def parse(frame: bytes) -> Frame | None:
    """Decode one complete frame."""
    if frame_length(frame) is None:
        return None
    return Frame(
        dest=int.from_bytes(frame[0:2], "little"),
        src=int.from_bytes(frame[2:4], "little"),
        control=frame[6],
        payload=frame[V3_HEADER_LEN:],
    )


class FrameStream:
    """Reassembles notification chunks into whole frames."""

    def __init__(self) -> None:
        """Start with an empty buffer."""
        self._buf = bytearray()
        self.dropped = 0

    @property
    def pending(self) -> int:
        """Bytes held back waiting for the rest of a frame."""
        return len(self._buf)

    def feed(self, data: bytes) -> list[Frame]:
        """Append received bytes and return every complete frame in them."""
        self._buf += data
        frames: list[Frame] = []
        while len(self._buf) >= V3_HEADER_LEN:
            total = frame_length(self._buf)
            if total is None:
                # Resynchronising discards a byte at a time. Counting them is
                # what tells a healthy stream apart from one where whole
                # messages are being thrown away unnoticed.
                self.dropped += 1
                del self._buf[:1]
                continue
            if len(self._buf) < total:
                break
            if (parsed := parse(bytes(self._buf[:total]))) is not None:
                frames.append(parsed)
            del self._buf[:total]
        return frames

    def reset(self) -> None:
        """Drop buffered bytes, e.g. after a reconnect."""
        self._buf.clear()
        self.dropped = 0
