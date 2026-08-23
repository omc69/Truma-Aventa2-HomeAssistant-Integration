"""Constants for the Truma Aventa integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "truma_aventa"

MANUFACTURER: Final = "Truma"
DEFAULT_MODEL: Final = "Aventa"

PLATFORMS: Final = [Platform.CLIMATE, Platform.LIGHT]
