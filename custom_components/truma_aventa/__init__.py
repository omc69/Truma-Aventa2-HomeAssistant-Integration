"""The Truma Aventa integration."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .connectivity import async_check_proxy
from .const import PLATFORMS
from .coordinator import TrumaConfigEntry, TrumaCoordinator
from .truma_ble.device import TrumaBleDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: TrumaConfigEntry) -> bool:
    """Set up a Truma appliance from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise ConfigEntryNotReady(
            f"{address} not found. The appliance advertises under a changing "
            "address, so it has to be in range and paired with this host"
        )

    # Checked before connecting, so the reason for a flapping link is visible
    # from the start rather than after the user has debugged it themselves.
    async_check_proxy(hass, entry.entry_id, address)

    device = TrumaBleDevice(ble_device, name=entry.title)
    coordinator = TrumaCoordinator(hass, entry, device)
    await coordinator.async_start()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TrumaConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded
