# Findings — Truma Aventa 2, our unit

Everything here comes from our own captures. It extends, and in places
corrects, [`truma-inetx-protocol-reference.md`](truma-inetx-protocol-reference.md),
which was written against a Combi heater behind an iNet X Panel.

## Correction: no UartPackage or MuldexPackage over BLE

The reference describes the stack as

```
UartPackage → MuldexPackage → TruMessageV3 → MBP → CBOR
```

Over BLE the first two layers are absent. An ATT payload **starts directly
with the 16-byte TruMessageV3 header**. Those two layers belong to the UART
transport.

A frame's length on the wire is `16 + PacketSize − 9`, and a message larger
than the MTU is split across several notifications, so frames must be cut by
the declared length rather than by packet boundaries.

## The BLE device

Advertised name `Truma iNetX-<suffix>`. Even though the unit is an Aventa with
no separate panel, it presents itself as an iNetX device.

Handles on our unit, and their roles:

| Handle | Characteristic | Traffic in capture 1 |
|---|---|---|
| `0x0019` | protocol version, read as ASCII `5.1` | 1 read |
| `0x0022` | **CMD** (`FC314001`) | 181 writes, 131 notifications |
| `0x0023` | CCCD of `0x0022` | notifications enabled |
| `0x0025` | **DATA_WRITE** (`FC314002`) | 27 write commands |
| `0x0027` | **DATA_READ** (`FC314003`) | 75 notifications |
| `0x0028` | CCCD of `0x0027` | notifications enabled |

Handles differ between units, so they are detected from the traffic rather
than hard-coded. The app never subscribes to `FC314004`, matching the
reference's warning that doing so breaks the transport.

## Device map of our unit

Discovered from parameter discovery in capture 1.

| Address | Identifies as | Notes |
|---|---|---|
| `0x0101` | panel | takes `RoomClimate` commands |
| `0x0601` | blePeripheral | `BleDeviceManagement`, `DeviceManagement` |
| `0x0702` | same serial as `0x0801` | `Identify` only |
| `0x0801` | **`Identify.Name` = `Aventa comfort 2. G`**, `Identify.Type` = 3 (AC) | **takes `AmbientLight` commands** |
| `0x0501` | app slot 1 | address assigned to us at registration |

`0x0801` is not in the reference's address table, which lists `0x0800` as
CAN_SLAVE and `0x0202` as `tinAventa`. Our Aventa is neither — so the address
has to be discovered at runtime rather than assumed.

`0x0702` and `0x0801` report the same serial number. They appear to be two
faces of the same appliance; only `0x0801` carries the functional topics.

## Command routing — confirmed

This is the part that cannot be guessed: a command sent to the wrong device is
silently ignored.

| Function | Topic | Destination |
|---|---|---|
| Air conditioning on/off and mode | `RoomClimate.Mode` | **panel `0x0101`** |
| Light on/off | `AmbientLight.Active` | **Aventa `0x0801`** |

## Commands confirmed from capture 1

Actions performed: app opened, air conditioning on, light on, light off, air
conditioning off.

| Time | Command | Destination |
|---|---|---|
| 20:07:15 | `{"tn": "RoomClimate", "pn": "Mode", "v": 1}` | panel |
| 20:07:21 | `{"tn": "AmbientLight", "pn": "Active", "v": 1}` | Aventa |
| 20:07:24 | `{"tn": "AmbientLight", "pn": "Active", "v": 0}` | Aventa |
| 20:07:31 | `{"tn": "RoomClimate", "pn": "Mode", "v": 0}` | panel |

Note that **switching the air conditioning on is `Mode = 1`**, which the
reference calls `ACC` — the automatic mode — not `2 = COOLING`. Whether the
app sends a different value when a specific mode is chosen still has to come
from a capture that changes modes.

## Identity

The app sends its identity as ordinary topic data, which is what the unit
remembers for pairing:

```
MobileIdentity.Muid     = <uppercase UUID>
MobileIdentity.Uuid     = <lowercase UUID>
MobileIdentity.UserName = "iPhone dev"
```

Two distinct UUIDs, one upper case and one lower case, plus a free-text name.
The actual values are deliberately not recorded here: the unit remembers them
and rejects a reconnect under a different identity, which makes them closer to
a credential than to a device fact.

The integration will have to generate a pair once and store it.

## Topics the app subscribes to

```
AirCirculation, AirCooling, AirHeating, AmbientLight, BatteryMngmt,
BleDeviceManagement, BluetoothDevice, Connect, DeviceManagement, EnergySrc,
ErrorReset, FreshWater, Fridge, GasBtl, GasControl, GreyWater, Identify,
Install, L1Bat, L2Bat, LinePower, MobileIdentity, Panel, PowerMgmt,
PowerSupply, Resources, RoomClimate, SubDevices, Switches, System, SystemTime,
Temperature, TimerConfig, Transfer, VBat, WaterHeating
```

`Fridge`, `SubDevices` and `SystemTime` do not appear in the reference.

## Still open

- Which value each **mode** button sends, and which modes this unit offers.
- **Fan level**: whether it is `AirCirculation.FanLevel` and to which device.
- **Target temperature**: expected as `RoomClimate.TgtTemp` in tenths of a
  degree, unconfirmed.
- Light **brightness** (`AmbientLight.LightStep`), if the unit has it.
- The **pairing** exchange — capture 1 was made from an already-paired phone.
