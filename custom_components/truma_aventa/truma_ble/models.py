"""State model for a Truma appliance."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .const import (
    FAN_MODES,
    MODE_COOLING,
    MODE_HEATING_AC,
    MODE_VENTILATING,
    ROOM_CLIMATE_MODES,
    TEMPERATURE_SCALE,
)


def tenths_to_degrees(value: int | None) -> float | None:
    """Convert a wire temperature to degrees."""
    return None if value is None else value / TEMPERATURE_SCALE


def degrees_to_tenths(value: float) -> int:
    """Convert degrees to the wire representation."""
    return round(value * TEMPERATURE_SCALE)


@dataclass(frozen=True, slots=True)
class TrumaState:
    """Everything known about the appliance right now.

    Values are stored exactly as they arrive on the wire; the conversion to
    something a user sees happens in the entities.
    """

    #: RoomClimate, owned by the panel.
    mode: int | None = None
    target_temperature: int | None = None

    #: AirCooling / AirHeating, owned by the appliance.
    cooling_fan_mode: int | None = None
    heating_fan_mode: int | None = None
    current_temperature: int | None = None

    #: AirCirculation, used while ventilating.
    fan_level: int | None = None

    #: AmbientLight.
    light_on: int | None = None
    light_step: int | None = None

    #: Identify, for the device registry.
    name: str | None = None
    serial_number: str | None = None
    software_version: str | None = None

    #: Every parameter seen, keyed "ADDR/Topic.Parameter".
    raw: dict[str, Any] = field(default_factory=dict)

    #: Addresses whose parameter discovery has run to its end. Until a device
    #: has finished reporting, what identifies it may still be missing, and
    #: entities built on a half-known identity would be built twice.
    complete: frozenset[str] = frozenset()

    def with_values(self, values: dict[str, Any]) -> TrumaState:
        """Return a copy with ``values`` applied."""
        return replace(self, **values)

    @property
    def mode_name(self) -> str | None:
        """Operating mode as a name, or None while unknown."""
        return ROOM_CLIMATE_MODES.get(self.mode) if self.mode is not None else None

    @property
    def active_fan_mode(self) -> int | None:
        """The fan setting that applies to the current operating mode.

        Cooling and heating each carry their own fan parameter, and while
        ventilating the fan lives in AirCirculation instead. Reading whichever
        happens to be set would show a stale value from a mode that is not
        running.
        """
        if self.mode == MODE_COOLING:
            return self.cooling_fan_mode
        if self.mode == MODE_HEATING_AC:
            return self.heating_fan_mode
        if self.mode == MODE_VENTILATING:
            return self.fan_level
        return self.cooling_fan_mode

    @property
    def fan_mode_name(self) -> str | None:
        """Current fan setting as a name."""
        value = self.active_fan_mode
        return FAN_MODES.get(value) if value is not None else None
