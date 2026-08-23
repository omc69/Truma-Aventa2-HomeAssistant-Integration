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

## The complete control surface

From capture 2 (every mode, target temperature, fan, light) plus the enum
definitions the unit itself reports during parameter discovery. These are not
inferred — the appliance names them.

### `RoomClimate.Mode` → panel `0x0101`

The master switch. Selecting a mode here is what turns the unit on.

| Value | Name |
|---|---|
| 0 | Off |
| 1 | ACC (automatic) |
| 2 | Cooling |
| 4 | HeatingAC |
| 5 | Ventilating |
| 6 | Dehumidifying |

`3 = Heating` from the reference is **absent** on this unit — an Aventa heats
via the heat pump, which is what `4 = HeatingAC` is.

### `RoomClimate.TgtTemp` → panel `0x0101`

Tenths of a degree, range 160–300, i.e. 16.0–30.0 °C. Confirmed by writes of
160, 260 and 220.

### `AirCooling.Mode` and `AirHeating.Mode` → Aventa `0x0801`

The fan/power level within cooling or heating. **This corrects the
reference**, which describes this parameter as `0 = COMFORT, 1 = FAST`. On our
unit:

| Value | Name |
|---|---|
| 0 | Auto |
| 1 | Low |
| 2 | Mid |
| 3 | High |
| 4 | Night |

`AirCooling.TgtTemp` and `AirHeating.TgtTemp` exist separately on `0x0801`,
same 160–300 range. The app writes the target temperature to `RoomClimate` on
the panel, not to these.

### `AirCirculation.FanLevel` → Aventa `0x0801`

Fan level in ventilating mode. Range **0–3** on our unit — the reference says
0–10, which does not apply here.

### `AmbientLight` → Aventa `0x0801`

| Parameter | Range | Notes |
|---|---|---|
| `Active` | 0 / 1 | confirmed by writes |
| `LightStep` | 0–100 | brightness in percent; reported by discovery, not yet exercised by a capture |

### Readings

`AirCooling.Temp` and `AirHeating.Temp` carry the current room temperature in
tenths of a degree, range −400 to 600. Read-only.

## Mapping to Home Assistant

The natural shape is one `climate` entity plus one `light` entity.

| HA concept | Source |
|---|---|
| `hvac_mode` off / auto / cool / heat_cool / fan_only / dry | `RoomClimate.Mode` 0 / 1 / 2 / 4 / 5 / 6 |
| `target_temperature`, 16–30 °C | `RoomClimate.TgtTemp` |
| `current_temperature` | `AirCooling.Temp` |
| `fan_mode` Auto / Low / Mid / High / Night | `AirCooling.Mode` or `AirHeating.Mode`, whichever matches the active mode; `AirCirculation.FanLevel` while ventilating |
| light on/off and brightness | `AmbientLight.Active`, `AmbientLight.LightStep` |

Note the split: mode and target temperature are panel parameters, everything
else belongs to the appliance.

## Pairing

### Plain Just Works pairing — no passkey

Captured. The exchange is ordinary Bluetooth Security Manager pairing, and
crucially it needs **no PIN at all**, which contradicts the reference's note
about a six-digit passkey.

The Security Manager parameters, decoded:

| Field | iPhone (initiator) | Aventa (responder) |
|---|---|---|
| IO Capability | `0x04` KeyboardDisplay | **`0x03` NoInputNoOutput** |
| OOB data | none | none |
| AuthReq | `0x2D` Bonding, MITM, Secure Connections | **`0x09` Bonding, Secure Connections** |
| Max key size | 16 | 16 |

KeyboardDisplay against NoInputNoOutput resolves to **Just Works** in the IO
capability matrix, and the appliance does not set the MITM bit — so no passkey
is requested or entered. What follows is a standard LE Secure Connections
exchange: public keys, confirm, random, DHKey check, then identity information
in both directions.

This matters for the integration: BlueZ can complete this unattended with a
NoInputNoOutput agent. Setup needs no PIN entry field.

### Finding the appliance behind a private address

The pairing runs against a **resolvable private address** that changes between
connections. The appliance's real identity address only appears inside the
pairing exchange, in Identity Address Information, as a **public** address.

An integration must therefore work from the identity address that BlueZ
resolves after bonding, not from whatever address a scan happens to report.

### Pairing has to be allowed first

A first attempt in the same capture was refused outright with
`SMP Pairing Failed, reason 0x05 Pairing Not Supported`; a second attempt two
minutes later succeeded. So the appliance does not accept pairing at any time
— it has to be put into a pairing state, or a client slot has to be free
(see the slot counts below). Worth surfacing in the integration's setup
instructions rather than presenting a bare failure.

### Application-level identity

Separate from the BLE bond, the app announces an identity as ordinary topic
data, and the appliance remembers it:

```
MobileIdentity.Muid     = <uppercase UUID>   per phone
MobileIdentity.Uuid     = <lowercase UUID>   shared between this user's phones
MobileIdentity.UserName = free text, shown in the app's device list
```

The two are not equivalent. A second phone visible in the same capture carries
a **different Muid but the same Uuid**, so the Uuid identifies the app or
account and the Muid the individual device. An integration should generate a
Muid of its own, keep it, and present a recognisable UserName.

### Connection slots

`BleDeviceManagement.NrFreeSlots` reports capacity by device type:

```
[{type: 12, nrOfSlots: 1}, {type: 9, nrOfSlots: 2}]
```

Two app slots were occupied simultaneously during the capture — ours as
`app1` (`0x0501`) and another phone as `app0` (`0x0500`) — so the appliance
serves several clients at once. Unlike the Tempra, this is not a
one-connection-at-a-time device.

## Still open
- `AmbientLight.LightStep` has never been written, only reported.
- Whether `AirCirculation.FanLevel` is the right control while ventilating, or
  whether the app uses `AirCooling.Mode` there too. Only one write was seen.

## A host Bluetooth adapter is not enough

The appliance advertises under a fast-rotating Resolvable Private Address and
accepts an encrypted reconnect only from a client that can resolve that address
back to the stored bond. A phone's controller does this; **BlueZ does not**.
It can complete the pairing, but every later reconnect arrives on an address it
cannot map to the key and the link is dropped.

This was established independently and exhaustively by
[rpodgorny/hass-truma-inetx](https://github.com/rpodgorny/hass-truma-inetx)
against the same protocol — IRK stored, LL-Privacy enabled, three different
adapters — and it fails at the controller level regardless of configuration.

Our own captures are consistent with it: the pairing exchange ran against
`4C:1D:BB:...` while the appliance's identity address is `FC:DE:C5:...`, and
the address differed again on later connections.

An ESPHome Bluetooth proxy built on **esp-idf** resolves private addresses in
the controller the way a phone does, and works. An Arduino-framework build does
not.

## Prior art

Two projects cover this protocol already, and both are worth knowing about:

- [daaaaan/truma-inetx-ble](https://github.com/daaaaan/truma-inetx-ble) —
  the protocol reference this work builds on, reverse engineered against a
  Combi D 4 E behind an iNet X panel. Mirrored in
  [`truma-inetx-protocol-reference.md`](truma-inetx-protocol-reference.md).
- [rpodgorny/hass-truma-inetx](https://github.com/rpodgorny/hass-truma-inetx) —
  a mature Home Assistant integration for an iNet X panel driving a Combi:
  heating, water heating, energy sources, a fan control, a custom dashboard
  card, and the proxy finding above. GPL-3.0.

Neither targets an Aventa. A Combi offers Off, Heat and Fan-only; an Aventa
adds cooling, dehumidifying and heat-pump heating, and has an ambient light.
That difference is why this integration exists. No code is taken from either —
this implementation is built from our own captures — but the facts they
established saved a great deal of time and are credited where used.
