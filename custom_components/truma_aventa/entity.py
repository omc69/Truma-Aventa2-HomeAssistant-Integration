"""Shared entity base for the Truma Aventa integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_MODEL, DOMAIN, MANUFACTURER
from .coordinator import TrumaCoordinator


class TrumaEntity(CoordinatorEntity[TrumaCoordinator]):
    """Base entity for the appliance."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TrumaCoordinator) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        device = coordinator.device
        state = coordinator.data
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.key)},
            connections={(CONNECTION_BLUETOOTH, device.address)},
            manufacturer=MANUFACTURER,
            model=state.name or DEFAULT_MODEL,
            name=device.name,
            serial_number=state.serial_number,
        )

    @property
    def available(self) -> bool:
        """Only available while the appliance is connected."""
        return super().available and self.coordinator.available
