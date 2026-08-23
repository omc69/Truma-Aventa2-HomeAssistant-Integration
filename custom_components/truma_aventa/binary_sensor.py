"""Binary sensor platform for the Truma Aventa integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TrumaConfigEntry, TrumaCoordinator
from .entity import TrumaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TrumaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the diagnostic binary sensor."""
    async_add_entities([TrumaConnectionSensor(entry.runtime_data)])


class TrumaConnectionSensor(TrumaEntity, BinarySensorEntity):
    """Whether the appliance is currently connected.

    Every other entity goes unavailable when the link drops, which tells you
    nothing about *why*. This one stays available and reports the link itself,
    so a connection that keeps flapping — the signature of a missing Bluetooth
    proxy — is visible on a dashboard and in history.
    """

    _attr_translation_key = "connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: TrumaCoordinator) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.address}_connection"

    @property
    def available(self) -> bool:
        """Always available: reporting "disconnected" is the point."""
        return True

    @property
    def is_on(self) -> bool:
        """Whether the appliance is connected and registered."""
        return self.coordinator.device.connected
