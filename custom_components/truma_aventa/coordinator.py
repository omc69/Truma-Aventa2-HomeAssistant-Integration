"""Push coordinator bridging the BLE link into Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .truma_ble import TrumaState
from .truma_ble.device import TrumaBleDevice

_LOGGER = logging.getLogger(__name__)

type TrumaConfigEntry = ConfigEntry[TrumaCoordinator]


class TrumaCoordinator(DataUpdateCoordinator[TrumaState]):
    """Holds one appliance connection and pushes its state to entities.

    There is no polling. The appliance pushes changes once subscribed, so
    ``update_interval`` stays None and updates arrive from the BLE callback.
    """

    config_entry: TrumaConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: TrumaConfigEntry, device: TrumaBleDevice
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {device.name}",
            update_interval=None,
        )
        self.device = device
        self.data = device.state
        self._unsubscribers: list[CALLBACK_TYPE] = []
        #: Base for entity unique ids and the device registry entry. The
        #: Bluetooth address is the obvious choice and the wrong one: the
        #: appliance rotates it, and two entries for one appliance then hand
        #: Home Assistant the same id twice, which makes it silently drop the
        #: second set of entities — including the ones belonging to the entry
        #: that actually holds the connection.
        self.key = entry.unique_id or device.address

    @property
    def available(self) -> bool:
        """Whether the appliance is connected and registered."""
        return self.device.connected

    async def async_start(self) -> None:
        """Connect and watch for advertisements."""
        self._unsubscribers.append(self.device.add_listener(self._handle_state))
        self._unsubscribers.append(
            bluetooth.async_register_callback(
                self.hass,
                self._handle_advertisement,
                {"address": self.device.address, "connectable": True},
                bluetooth.BluetoothScanningMode.ACTIVE,
            )
        )
        await self.device.async_start()

    async def async_stop(self) -> None:
        """Tear everything down."""
        while self._unsubscribers:
            self._unsubscribers.pop()()
        await self.device.async_stop()

    @callback
    def _handle_state(self, state: TrumaState) -> None:
        self.async_set_updated_data(state)

    @callback
    def _handle_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Adopt the freshest BLEDevice.

        The appliance advertises under a resolvable private address that
        changes between connections, so the object handed to bleak has to be
        refreshed rather than kept from setup.
        """
        self.device.set_ble_device(service_info.device)
