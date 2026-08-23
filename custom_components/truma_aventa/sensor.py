"""Sensor platform: every parameter the bus reports.

Parameter discovery returns everything each device on the bus knows about
itself. The climate and light entities model the handful a user acts on;
these sensors expose the rest as it arrives, so nothing the appliance reports
is invisible.

One device answers on several addresses -- on this system the interface
answers on three, all reporting the same parameters with the same
``Identify.UniqueID``. Addresses that share an identity are folded into one
Home Assistant device, which is the difference between a couple of hundred
entities and a thousand.

Entities appear as their parameters do; a device that only speaks up later
still gets its sensors without a reload.
"""

from __future__ import annotations

import re
from typing import Any, Final

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import TrumaConfigEntry, TrumaCoordinator

#: Parameters are keyed "ADDR/Topic.Parameter" by the protocol layer.
_KEY: Final = re.compile(r"^([0-9A-F]{4})/([^./]+)\.([^./]+)$")

#: Temperatures arrive in tenths of a degree. Only parameters seen carrying a
#: real temperature are converted; the appliance also reports raw sensor
#: readings, which use -299 to mean "nothing connected" and are left alone.
_TEMPERATURES: Final = frozenset(
    {
        "AirCooling.Temp",
        "AirCooling.TgtTemp",
        "AirHeating.Temp",
        "AirHeating.TgtTemp",
        "RoomClimate.TgtTemp",
        "Temperature.Internal",
    }
)

#: What identifies a device across the addresses it answers on, best first.
_IDENTITY_PARAMETERS: Final = ("Identify.UniqueID", "Identify.SerialNr")

#: A state may not exceed 255 characters.
_MAX_STATE: Final = 255


def _readable(value: Any) -> str | int | float | None:
    """Render a parameter value as something a state can hold."""
    if value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return value.hex()[:_MAX_STATE]
    return str(value)[:_MAX_STATE]


def _identity(raw: dict[str, Any], address: str) -> str:
    """What to call the device answering on this address."""
    for parameter in _IDENTITY_PARAMETERS:
        if value := raw.get(f"{address}/{parameter}"):
            return str(value)
    return f"address-{address}"


def _group_addresses(
    raw: dict[str, Any], complete: frozenset[str]
) -> dict[str, list[str]]:
    """Map each device identity to the addresses it answers on.

    Only addresses that have finished reporting are grouped: what identifies a
    device arrives partway through its answers, and grouping it earlier would
    file the same parameter first under an address and then under an identity.
    """
    groups: dict[str, list[str]] = {}
    for key in raw:
        if (match := _KEY.match(key)) is None:
            continue
        address = match.group(1)
        if address not in complete:
            continue
        addresses = groups.setdefault(_identity(raw, address), [])
        if address not in addresses:
            addresses.append(address)
    for addresses in groups.values():
        addresses.sort()
    return groups


def _parameters(raw: dict[str, Any], addresses: list[str]) -> set[str]:
    """Every "Topic.Parameter" reported by any address of one device."""
    found: set[str] = set()
    for key in raw:
        if (match := _KEY.match(key)) is not None and match.group(1) in addresses:
            found.add(f"{match.group(2)}.{match.group(3)}")
    return found


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TrumaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one sensor per reported parameter, and more as they appear."""
    coordinator = entry.runtime_data
    known: set[tuple[str, str]] = set()

    @callback
    def _async_add_known() -> None:
        data = coordinator.data
        raw = data.raw
        fresh: list[TrumaParameterSensor] = []
        for identity, addresses in _group_addresses(raw, data.complete).items():
            for parameter in sorted(_parameters(raw, addresses)):
                if (identity, parameter) in known:
                    continue
                known.add((identity, parameter))
                fresh.append(
                    TrumaParameterSensor(coordinator, identity, addresses, parameter)
                )
        if fresh:
            async_add_entities(fresh)

    _async_add_known()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_known))


class TrumaParameterSensor(CoordinatorEntity[TrumaCoordinator], SensorEntity):
    """One parameter of one device on the bus."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: TrumaCoordinator,
        identity: str,
        addresses: list[str],
        parameter: str,
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._addresses = list(addresses)
        self._parameter = parameter
        topic, _, name = parameter.partition(".")
        self._attr_name = f"{topic} {name}"
        self._attr_unique_id = f"{coordinator.key}_{identity}_{parameter}"
        if parameter in _TEMPERATURES:
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_suggested_display_precision = 1
        self._attr_device_info = self._build_device_info(coordinator, identity)

    def _build_device_info(
        self, coordinator: TrumaCoordinator, identity: str
    ) -> DeviceInfo:
        """Describe the bus device this parameter belongs to."""
        name = self._first("Identify.Name")
        major = self._first("Identify.SwMaj")
        minor = self._first("Identify.SwMin")
        serial = self._first("Identify.SerialNr")
        return DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.key}:{identity}")},
            manufacturer=MANUFACTURER,
            model=str(name) if name else None,
            name=str(name) if name else f"Truma 0x{self._addresses[0]}",
            serial_number=str(serial) if serial else None,
            sw_version=(
                f"{major}.{minor}" if major is not None and minor is not None else None
            ),
            via_device=(DOMAIN, coordinator.key),
        )

    def _first(self, parameter: str) -> Any:
        """The value from whichever of this device's addresses reports it."""
        raw = self.coordinator.data.raw
        for address in self._addresses:
            if (value := raw.get(f"{address}/{parameter}")) is not None:
                return value
        return None

    @property
    def available(self) -> bool:
        """Only available while the appliance is connected."""
        return super().available and self.coordinator.available

    @property
    def native_value(self) -> str | int | float | None:
        """The parameter's current value."""
        value = self._first(self._parameter)
        if self._attr_device_class is SensorDeviceClass.TEMPERATURE:
            return value / 10 if isinstance(value, (int, float)) else None
        return _readable(value)
