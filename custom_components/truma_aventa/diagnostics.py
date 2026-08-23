"""Diagnostics for the Truma Aventa integration.

The dump includes every topic parameter the appliance has reported, not just
the ones mapped to entities. Models differ in which topics they expose, so a
dump from an unfamiliar unit is what makes supporting it possible.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import TrumaConfigEntry

#: Identifiers that say which appliance this is, or which client it trusts.
TO_REDACT = {"MobileIdentity.Muid", "MobileIdentity.Uuid", "Identify.SerialNr"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TrumaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    state = coordinator.data
    return {
        "device": {
            "name": state.name,
            "connected": coordinator.device.connected,
        },
        "state": {
            "mode": state.mode,
            "mode_name": state.mode_name,
            "target_temperature": state.target_temperature,
            "current_temperature": state.current_temperature,
            "fan_mode": state.fan_mode_name,
            "light_on": state.light_on,
            "light_step": state.light_step,
        },
        "parameters": {
            key: ("**redacted**" if key in TO_REDACT else value)
            for key, value in sorted(state.raw.items())
        },
    }
