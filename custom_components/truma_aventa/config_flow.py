"""Config flow for the Truma Aventa integration.

The appliance advertises under a resolvable private address that changes
between connections, and it will only talk to a host it has been paired with.
Both of those shape this flow: discovery is by name rather than by a fixed
address, and setup tells the user to pair first rather than failing obscurely
when the appliance refuses.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN
from .pairing import async_pair
from .truma_ble import ADVERTISED_NAME_PREFIX, TRUMA_MANUFACTURER_ID
from .truma_ble.const import KNOWN_INTERFACE_UUIDS


def _is_truma(info: BluetoothServiceInfoBleak) -> bool:
    """Whether an advertisement looks like a Truma appliance.

    Three ways, because none of them is present in every advertisement: the
    interface service UUID, the manufacturer id, and finally the local name.
    """
    if any(uuid in info.service_uuids for uuid in KNOWN_INTERFACE_UUIDS):
        return True
    if TRUMA_MANUFACTURER_ID in info.manufacturer_data:
        return True
    return bool(info.name) and info.name.startswith(ADVERTISED_NAME_PREFIX)


class TrumaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle discovery and manual setup."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle an appliance discovered by the Bluetooth integration."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered appliance, bonding with it first."""
        assert self._discovery is not None
        if user_input is not None:
            return await self._async_pair_and_create(
                self._discovery.address, self._discovery.name
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._discovery.name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick an appliance from the ones in range."""
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            result = await self._async_pair_and_create(
                address, self._discovered.get(address, address)
            )
            if result is not None:
                return result
            errors["base"] = "cannot_pair"

        configured = self._async_current_ids()
        self._discovered = {
            info.address: f"{info.name} ({info.address})"
            for info in async_discovered_service_info(self.hass, connectable=True)
            if _is_truma(info) and info.address not in configured
        }
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(self._discovered)}
            ),
            errors=errors,
        )

    async def _async_pair_and_create(
        self, address: str, title: str
    ) -> ConfigFlowResult | None:
        """Bond with the appliance, then create the entry.

        Bonding happens here rather than at first connect because the appliance
        only accepts a client it has bonded with, and because a failure at this
        point can still be explained to the person standing in front of it —
        the appliance has to be in its pairing state and have a free client
        slot.
        """
        ble_device = async_ble_device_from_address(self.hass, address, connectable=True)
        if ble_device is None:
            return self.async_abort(reason="not_reachable")
        if not await async_pair(ble_device):
            return None
        return self.async_create_entry(title=title, data={CONF_ADDRESS: address})
