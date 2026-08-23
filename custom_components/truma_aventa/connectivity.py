"""Checks whether this appliance can actually be reached, and says why not.

The appliance rotates its Bluetooth address and only accepts an encrypted
reconnect from a client that can resolve that address back to the bond. A host
adapter running BlueZ cannot: it pairs, then loses every reconnect. An ESPHome
proxy on an esp-idf build resolves the address in its controller and works.

Without this check the symptom is a link that connects and drops in a loop,
which looks like a bug in the integration rather than a missing proxy.
"""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ISSUE_NO_PROXY = "no_bluetooth_proxy"


@callback
def async_has_proxy_path(hass: HomeAssistant, address: str) -> bool | None:
    """Whether a remote Bluetooth proxy can reach the appliance.

    Returns None when Home Assistant is too old or too new to ask in the way
    we know how -- in that case nothing is claimed either way, because a wrong
    warning is worse than none.
    """
    try:
        from habluetooth import BaseHaRemoteScanner
    except ImportError:  # pragma: no cover - depends on the HA version
        return None

    try:
        devices = bluetooth.async_scanner_devices_by_address(
            hass, address, connectable=True
        )
    except Exception:
        return None

    if not devices:
        return None
    return any(isinstance(device.scanner, BaseHaRemoteScanner) for device in devices)


@callback
def async_check_proxy(hass: HomeAssistant, entry_id: str, address: str) -> None:
    """Raise or clear the "no proxy" repair issue for this appliance."""
    has_proxy = async_has_proxy_path(hass, address)
    if has_proxy is None:
        return

    if has_proxy:
        ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_NO_PROXY}_{entry_id}")
        return

    _LOGGER.warning(
        "%s is only reachable through this host's own Bluetooth adapter. "
        "The appliance rotates its Bluetooth address, which a host adapter "
        "may not resolve after a drop; an ESPHome Bluetooth proxy on an "
        "esp-idf build reconnects reliably and reaches further",
        address,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{ISSUE_NO_PROXY}_{entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_NO_PROXY,
        translation_placeholders={"address": address},
        learn_more_url=(
            "https://github.com/omc69/Truma-Aventa2-HomeAssistant-Integration"
            "#an-esp32-bluetooth-proxy-is-required"
        ),
    )
