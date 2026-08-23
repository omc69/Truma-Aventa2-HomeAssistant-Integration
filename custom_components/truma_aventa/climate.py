"""Climate platform for the Truma Aventa integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TrumaConfigEntry, TrumaCoordinator
from .entity import TrumaEntity
from .truma_ble import (
    FAN_MODES,
    MAX_TEMPERATURE,
    MIN_TEMPERATURE,
    MODE_AUTO,
    MODE_COOLING,
    MODE_DEHUMIDIFYING,
    MODE_HEATING_AC,
    MODE_OFF,
    MODE_VENTILATING,
    TOPIC_AIR_CIRCULATION,
    TOPIC_AIR_COOLING,
    TOPIC_AIR_HEATING,
    TOPIC_ROOM_CLIMATE,
    degrees_to_tenths,
    tenths_to_degrees,
)

#: Home Assistant's modes against the appliance's own. Mode 3, plain heating,
#: is deliberately absent: an Aventa heats through the heat pump, which is
#: mode 4, and only the modes the unit reports are offered.
_HVAC_TO_MODE: dict[HVACMode, int] = {
    HVACMode.OFF: MODE_OFF,
    HVACMode.AUTO: MODE_AUTO,
    HVACMode.COOL: MODE_COOLING,
    HVACMode.HEAT_COOL: MODE_HEATING_AC,
    HVACMode.FAN_ONLY: MODE_VENTILATING,
    HVACMode.DRY: MODE_DEHUMIDIFYING,
}
_MODE_TO_HVAC = {mode: hvac for hvac, mode in _HVAC_TO_MODE.items()}

_FAN_MODE_TO_VALUE = {name: value for value, name in FAN_MODES.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TrumaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the climate entity."""
    async_add_entities([TrumaClimate(entry.runtime_data)])


class TrumaClimate(TrumaEntity, ClimateEntity):
    """The air conditioner itself."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = list(_HVAC_TO_MODE)
    _attr_fan_modes = list(_FAN_MODE_TO_VALUE)
    _attr_min_temp = MIN_TEMPERATURE
    _attr_max_temp = MAX_TEMPERATURE
    _attr_target_temperature_step = 1.0
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: TrumaCoordinator) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.device.address

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Current operating mode."""
        mode = self.coordinator.data.mode
        return _MODE_TO_HVAC.get(mode) if mode is not None else None

    @property
    def current_temperature(self) -> float | None:
        """Room temperature as the appliance measures it."""
        return tenths_to_degrees(self.coordinator.data.current_temperature)

    @property
    def target_temperature(self) -> float | None:
        """Configured target temperature."""
        return tenths_to_degrees(self.coordinator.data.target_temperature)

    @property
    def fan_mode(self) -> str | None:
        """Fan setting that applies to the running mode."""
        return self.coordinator.data.fan_mode_name

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Switch the appliance on, off, or to another mode."""
        if (mode := _HVAC_TO_MODE.get(hvac_mode)) is None:
            raise HomeAssistantError(f"Unsupported mode {hvac_mode}")
        await self._async_write(TOPIC_ROOM_CLIMATE, "Mode", mode)

    async def async_turn_on(self) -> None:
        """Turn on, in the automatic mode the app also uses."""
        await self._async_write(TOPIC_ROOM_CLIMATE, "Mode", MODE_AUTO)

    async def async_turn_off(self) -> None:
        """Turn off."""
        await self._async_write(TOPIC_ROOM_CLIMATE, "Mode", MODE_OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self._async_write(
            TOPIC_ROOM_CLIMATE, "TgtTemp", degrees_to_tenths(temperature)
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan level.

        Which parameter carries the fan depends on the running mode: cooling
        and heating each have their own, and while ventilating it lives in
        AirCirculation. Writing the wrong one is accepted but has no effect.
        """
        if (value := _FAN_MODE_TO_VALUE.get(fan_mode)) is None:
            raise HomeAssistantError(f"Unsupported fan mode {fan_mode}")
        mode = self.coordinator.data.mode
        if mode == MODE_VENTILATING:
            await self._async_write(TOPIC_AIR_CIRCULATION, "FanLevel", value)
        elif mode == MODE_HEATING_AC:
            await self._async_write(TOPIC_AIR_HEATING, "Mode", value)
        else:
            await self._async_write(TOPIC_AIR_COOLING, "Mode", value)

    async def _async_write(self, topic: str, parameter: str, value: Any) -> None:
        try:
            await self.coordinator.device.async_set_parameter(topic, parameter, value)
        except Exception as err:  # noqa: BLE001 - surfaced to the user as-is
            raise HomeAssistantError(
                f"Could not send {topic}.{parameter} to the appliance: {err}"
            ) from err
        # The appliance echoes the change back as a topic update, so nothing is
        # assumed here -- the state follows what it actually did.
