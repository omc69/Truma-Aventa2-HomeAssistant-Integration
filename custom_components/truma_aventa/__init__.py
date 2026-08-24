"""The Truma Aventa integration."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .connectivity import async_check_proxy
from .const import PLATFORMS
from .coordinator import TrumaConfigEntry, TrumaCoordinator
from .identity import CONF_IDENTITY, new_identity
from .truma_ble.device import TrumaBleDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: TrumaConfigEntry) -> bool:
    """Set up a Truma appliance from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        # The stored address can go stale: the appliance rotates its address,
        # and a host that has not resolved it back to one identity will only
        # ever see the current one. The advertised name does not change, so it
        # is the way back to the device.
        ble_device = _async_find_by_name(hass, entry.unique_id)
        if ble_device is not None:
            address = ble_device.address
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_ADDRESS: address}
            )
            _LOGGER.debug("%s moved to %s", entry.unique_id, address)

    if ble_device is None:
        raise ConfigEntryNotReady(
            f"{address} not found. The appliance advertises under a changing "
            "address, so it has to be in range and paired with this host"
        )

    # Checked before connecting, so the reason for a flapping link is visible
    # from the start rather than after the user has debugged it themselves.
    async_check_proxy(hass, entry.entry_id, address)

    # Generated once and kept: the appliance remembers the clients it knows,
    # so an identity invented afresh on every start would look like a new
    # client each time.
    identity = entry.data.get(CONF_IDENTITY)
    if not identity:
        identity = new_identity()
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_IDENTITY: identity}
        )

    device = TrumaBleDevice(ble_device, identity=identity, name=entry.title)
    coordinator = TrumaCoordinator(hass, entry, device)
    await coordinator.async_start()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _async_find_by_name(hass: HomeAssistant, name: str | None):
    """Locate the appliance by its advertised name."""
    if not name:
        return None
    for info in bluetooth.async_discovered_service_info(hass, connectable=True):
        if info.name == name:
            return info.device
    return None


async def async_unload_entry(hass: HomeAssistant, entry: TrumaConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: TrumaConfigEntry,
    device: dr.DeviceEntry,
) -> bool:
    """Allow a device that is no longer reported to be deleted.

    Which devices the bus lists can change -- and an earlier version of this
    integration made one out of every address that answered, including the
    bookkeeping endpoints. Those entries have to be removable by hand rather
    than sitting in the list forever.
    """
    return True
