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


def _unique_id(info: BluetoothServiceInfoBleak) -> str:
    """A handle for the appliance that survives its address changing.

    The appliance rotates its Bluetooth address, so keying an entry on the
    address produces a fresh "new device" every few minutes -- three config
    entries appeared for one appliance during testing. The advertised name
    carries the unit's own identifier and does not change.
    """
    return info.name or info.address


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
        self._address: str | None = None
        self._title: str | None = None
        self._unique_ids: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle an appliance discovered by the Bluetooth integration."""
        await self.async_set_unique_id(_unique_id(discovery_info))
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
            self._address = self._discovery.address
            self._title = self._discovery.name
            return await self.async_step_pair()

        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._discovery.name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick an appliance from the ones in range."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(
                self._unique_ids.get(address, address), raise_on_progress=False
            )
            self._abort_if_unique_id_configured()
            self._address = address
            self._title = self._discovered.get(address, address)
            return await self.async_step_pair()

        configured = self._async_current_ids()
        self._discovered = {}
        self._unique_ids = {}
        for info in async_discovered_service_info(self.hass, connectable=True):
            if not _is_truma(info) or _unique_id(info) in configured:
                continue
            self._discovered[info.address] = f"{info.name} ({info.address})"
            self._unique_ids[info.address] = _unique_id(info)
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(self._discovered)}
            ),
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for pairing to be started on the appliance, then bond.

        The order matters and cannot be worked around. The appliance accepts a
        new client only while it is in its pairing state, and that state lasts
        a short while — so the person has to press the button on the unit
        *before* this step runs, not after it has already failed. Pairing
        silently in the background would fail the first time for everyone.
        """
        assert self._address is not None

        if user_input is None:
            return self.async_show_form(
                step_id="pair",
                description_placeholders={"name": self._title or self._address},
            )

        ble_device = async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if ble_device is None:
            return self.async_show_form(
                step_id="pair",
                description_placeholders={"name": self._title or self._address},
                errors={"base": "not_reachable"},
            )

        if not await async_pair(ble_device):
            # Stay on this step rather than abort: the usual remedy is to start
            # pairing on the unit again and press Submit once more, and our own
            # captures show a refusal followed by a successful retry.
            return self.async_show_form(
                step_id="pair",
                description_placeholders={"name": self._title or self._address},
                errors={"base": "cannot_pair"},
            )

        return self.async_create_entry(
            title=self._title or self._address, data={CONF_ADDRESS: self._address}
        )
