"""Standalone BLE protocol layer for Truma appliances.

Free of Home Assistant imports, so the framing and decoding can be exercised
and unit tested on their own. ``TrumaBleDevice`` lives in ``.device`` and is
imported from there directly, keeping bleak out of the parts worth testing.
"""

from __future__ import annotations

from .const import (
    ADVERTISED_NAME_PREFIX,
    ADVERTISED_SERVICE_UUIDS,
    FAN_MODES,
    KNOWN_INTERFACE_UUIDS,
    MAX_LIGHT_STEP,
    MAX_TEMPERATURE,
    MIN_TEMPERATURE,
    MODE_AUTO,
    MODE_COOLING,
    MODE_DEHUMIDIFYING,
    MODE_HEATING_AC,
    MODE_OFF,
    MODE_VENTILATING,
    ROOM_CLIMATE_MODES,
    SERVICE_UUID,
    TOPIC_AIR_CIRCULATION,
    TOPIC_AIR_COOLING,
    TOPIC_AIR_HEATING,
    TOPIC_AMBIENT_LIGHT,
    TOPIC_ROOM_CLIMATE,
    TRUMA_MANUFACTURER_ID,
)
from .frames import Frame, FrameStream, build, build_mbp, parse
from .models import TrumaState, degrees_to_tenths, tenths_to_degrees

__all__ = [
    "ADVERTISED_NAME_PREFIX",
    "ADVERTISED_SERVICE_UUIDS",
    "FAN_MODES",
    "KNOWN_INTERFACE_UUIDS",
    "MAX_LIGHT_STEP",
    "MAX_TEMPERATURE",
    "MIN_TEMPERATURE",
    "MODE_AUTO",
    "MODE_COOLING",
    "MODE_DEHUMIDIFYING",
    "MODE_HEATING_AC",
    "MODE_OFF",
    "MODE_VENTILATING",
    "ROOM_CLIMATE_MODES",
    "SERVICE_UUID",
    "TOPIC_AIR_CIRCULATION",
    "TOPIC_AIR_COOLING",
    "TOPIC_AIR_HEATING",
    "TOPIC_AMBIENT_LIGHT",
    "TOPIC_ROOM_CLIMATE",
    "TRUMA_MANUFACTURER_ID",
    "Frame",
    "FrameStream",
    "TrumaState",
    "build",
    "build_mbp",
    "degrees_to_tenths",
    "parse",
    "tenths_to_degrees",
]
