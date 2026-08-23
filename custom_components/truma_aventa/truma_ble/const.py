"""Protocol constants for Truma appliances speaking the iNet X BLE protocol.

Derived from HCI captures of a Truma Aventa comfort 2nd generation, and from
the protocol write-up at https://github.com/daaaaan/truma-inetx-ble, which
documented the same protocol against a Combi heater behind an iNet X panel.
Where the two disagree, the captures win and the difference is noted.
"""

from __future__ import annotations

from typing import Final

# --- GATT ------------------------------------------------------------------

#: All Truma UUIDs share this suffix.
UUID_SUFFIX: Final = "-f3b2-11e8-8eb2-f2801f1b9fd1"

SERVICE_UUID: Final = f"f47bbbac{UUID_SUFFIX}"

#: Transport control. Short frames both ways.
CMD_CHAR_UUID: Final = f"fc314001{UUID_SUFFIX}"
#: Outbound messages.
DATA_WRITE_CHAR_UUID: Final = f"fc314002{UUID_SUFFIX}"
#: Inbound messages.
DATA_READ_CHAR_UUID: Final = f"fc314003{UUID_SUFFIX}"
#: Never subscribe to this one -- doing so breaks the transport.
CMD_ALT_CHAR_UUID: Final = f"fc314004{UUID_SUFFIX}"

#: Advertised by the appliance; used to recognise it while scanning.
#:
#: The local name is the obvious handle but the least reliable one -- it is
#: not in every advertisement. These service UUIDs are, and they also say what
#: kind of appliance is behind them: an Aventa advertises FC310003, which the
#: protocol reference calls "Interface AC".
ADVERTISED_NAME_PREFIX: Final = "Truma"
TRUMA_MANUFACTURER_ID: Final = 3187

ADVERTISED_SERVICE_UUIDS: Final = (
    f"fc310003{UUID_SUFFIX}",  # Interface AC
    f"fc314000{UUID_SUFFIX}",  # data service group
)

#: Every panel and interface type the protocol defines, so an appliance that
#: is not an Aventa is still recognised rather than silently ignored.
KNOWN_INTERFACE_UUIDS: Final = tuple(
    f"fc31000{index}{UUID_SUFFIX}" for index in range(7)
)

# --- Transport FSM (on CMD_CHAR) -------------------------------------------

OP_INIT_DATA_TRANSFER: Final = 0x01
OP_MSG_ACK_CONFIRM: Final = 0x03
OP_READY_STATUS: Final = 0x81
OP_ACK_DATA_TRANSFER: Final = 0xF0
OP_MSG_ACK: Final = 0x83

#: Sent back for every inbound data frame.
ACK_DATA: Final = bytes([OP_ACK_DATA_TRANSFER, 0x01])
#: Sent back for every inbound 83 xx 00 message acknowledgement.
CONFIRM_MSG_ACK: Final = bytes([OP_MSG_ACK_CONFIRM, 0x00])

# --- TruMessageV3 ----------------------------------------------------------

#: Over BLE the ATT payload *is* the V3 message. The UartPackage and
#: MuldexPackage layers described in the reference belong to the UART
#: transport and are absent here.
V3_HEADER_LEN: Final = 16

#: The header's size field counts the payload plus this.
V3_SIZE_OVERHEAD: Final = 9

CONTROL_REGISTRATION: Final = 0x01
CONTROL_DISCOVERY: Final = 0x02
CONTROL_MBP: Final = 0x03

CONTROL_TYPES: Final[dict[int, str]] = {
    0x01: "REGISTRATION",
    0x02: "DISCOVERY",
    0x03: "MBP",
    0x04: "FILE_MANAGER",
    0x05: "SECURITY",
    0x06: "FIRMWARE_UPDATE",
    0x0A: "NONE",
}

# --- Message broker sub-protocol -------------------------------------------

MBP_INFO: Final = 0x00
MBP_WRITE: Final = 0x01
MBP_SUBSCRIBE: Final = 0x02
MBP_PARAM_DISCOVERY: Final = 0x04
MBP_SUBSCRIBE_RESPONSE: Final = 0x82
MBP_PARAM_DISCOVERY_RESPONSE: Final = 0x84

# --- Device addresses ------------------------------------------------------

ADDR_MESSAGE_BROKER: Final = 0x0000

#: Owns RoomClimate. The protocol reference calls this address the panel,
#: because its system had one; on an Aventa with no separate panel the same
#: address identifies itself as "iNet X Interface AC", device type INTERFACE —
#: the appliance's own BLE interface. Same address, same role, different box.
ADDR_INTERFACE: Final = 0x0101
ADDR_UNREGISTERED: Final = 0xFFFF
ADDR_BROADCAST: Final = 0xFFFF

#: Highest plausible device address, used to sanity-check a candidate header.
MAX_DEVICE_ADDRESS: Final = 0x0FFF

#: Protocol version the app announces during registration.
PROTOCOL_VERSION: Final = [5, 1]

# --- Topics and parameters -------------------------------------------------

TOPIC_ROOM_CLIMATE: Final = "RoomClimate"
TOPIC_AIR_COOLING: Final = "AirCooling"
TOPIC_AIR_HEATING: Final = "AirHeating"
TOPIC_AIR_CIRCULATION: Final = "AirCirculation"
TOPIC_AMBIENT_LIGHT: Final = "AmbientLight"
TOPIC_IDENTIFY: Final = "Identify"
TOPIC_MOBILE_IDENTITY: Final = "MobileIdentity"

TOPIC_AIR_DEHUMID: Final = "AirDehumid"

#: Everything worth following. Subscribed in batches.
SUBSCRIBED_TOPICS: Final = (
    TOPIC_ROOM_CLIMATE,
    TOPIC_AIR_COOLING,
    TOPIC_AIR_HEATING,
    TOPIC_AIR_CIRCULATION,
    TOPIC_AIR_DEHUMID,
    TOPIC_AMBIENT_LIGHT,
    TOPIC_IDENTIFY,
)

MAX_TOPICS_PER_SUBSCRIBE: Final = 10

# --- Enumerations, as the appliance itself reports them --------------------

MODE_OFF: Final = 0
MODE_AUTO: Final = 1
MODE_COOLING: Final = 2
MODE_HEATING: Final = 3
MODE_HEATING_AC: Final = 4
MODE_VENTILATING: Final = 5
MODE_DEHUMIDIFYING: Final = 6

#: An Aventa heats through the heat pump, so it offers HeatingAC and not the
#: plain Heating a Combi has. The value is kept for completeness.
ROOM_CLIMATE_MODES: Final[dict[int, str]] = {
    MODE_OFF: "off",
    MODE_AUTO: "auto",
    MODE_COOLING: "cooling",
    MODE_HEATING: "heating",
    MODE_HEATING_AC: "heating_ac",
    MODE_VENTILATING: "ventilating",
    MODE_DEHUMIDIFYING: "dehumidifying",
}

#: AirCooling.Mode / AirHeating.Mode. The reference calls these Comfort/Fast;
#: the appliance reports them as fan levels.
FAN_MODES: Final[dict[int, str]] = {
    0: "auto",
    1: "low",
    2: "mid",
    3: "high",
    4: "night",
}

#: Temperatures are transported in tenths of a degree.
TEMPERATURE_SCALE: Final = 10
MIN_TEMPERATURE: Final = 16.0
MAX_TEMPERATURE: Final = 30.0

#: AmbientLight.LightStep is a percentage.
MIN_LIGHT_STEP: Final = 0
MAX_LIGHT_STEP: Final = 100
