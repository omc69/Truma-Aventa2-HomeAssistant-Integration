"""Light platform for the Truma Aventa integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TrumaConfigEntry, TrumaCoordinator
from .entity import TrumaEntity
from .truma_ble import MAX_LIGHT_STEP, TOPIC_AMBIENT_LIGHT

#: Home Assistant works in 0-255, the appliance in percent.
_HA_BRIGHTNESS_MAX = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TrumaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the light entity."""
    async_add_entities([TrumaLight(entry.runtime_data)])


class TrumaLight(TrumaEntity, LightEntity):
    """The appliance's ambient light."""

    _attr_translation_key = "ambient_light"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator: TrumaCoordinator) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.key}_ambient_light"

    @property
    def is_on(self) -> bool | None:
        """Whether the light is on."""
        active = self.coordinator.data.light_on
        return None if active is None else bool(active)

    @property
    def brightness(self) -> int | None:
        """Brightness, converted from the appliance's percentage."""
        step = self.coordinator.data.light_step
        if step is None:
            return None
        return round(step * _HA_BRIGHTNESS_MAX / MAX_LIGHT_STEP)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on, optionally at a given brightness."""
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            step = round(brightness * MAX_LIGHT_STEP / _HA_BRIGHTNESS_MAX)
            await self._async_write("LightStep", step)
        await self._async_write("Active", 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._async_write("Active", 0)

    async def _async_write(self, parameter: str, value: Any) -> None:
        try:
            await self.coordinator.device.async_set_parameter(
                TOPIC_AMBIENT_LIGHT, parameter, value
            )
        except Exception as err:  # noqa: BLE001 - surfaced to the user as-is
            raise HomeAssistantError(
                f"Could not send AmbientLight.{parameter} to the appliance: {err}"
            ) from err
