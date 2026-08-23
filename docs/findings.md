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

Counted per address, from a sweep where each device was asked separately.

| Address | Identifies as | Own parameters |
|---|---|---|
| `0x0101` | **`iNet X Interface AC`**, `Identify.Type` = 10 (INTERFACE), serial `IIIRTEU-A-…`, sw 3.5 | 60 — takes `RoomClimate` commands |
| `0x0801` | **`Aventa comfort 2. G`**, `Identify.Type` = 3 (AC), serial `AVRLWZZ-A-…`, sw 1.6 | 32 — takes `AmbientLight`, `AirCooling`, `AirHeating` |
| `0x0702` | same serial as `0x0801` | 7, `Identify` only |
| `0x0601` | blePeripheral | 10 |
| `0x0600` | `Blemcu`, `DeviceManagement` | 6 |
| `0x0800` | `DeviceManagement`, `ErrorReset` | 6 |
| `0x0200`, `0x0400` | `DeviceManagement` only | 3 each |
| `0x0500` | app slot 0 | 6 |
| `0x0501` | app slot 1 | address assigned to us at registration |

Careful with cumulative counts: an inventory printed after each burst grows as
the sweep proceeds, so "the appliance reports 88 parameters" was really "88
parameters had been seen by then, across every device". Keyed per address, the
air conditioning reports 32.

`0x0801` is not in the reference's address table, which lists `0x0800` as
CAN_SLAVE and `0x0202` as `tinAventa`. Our Aventa is neither — so the address
has to be discovered at runtime rather than assumed.

`0x0702` and `0x0801` report the same serial number. They appear to be two
faces of the same appliance; only `0x0801` carries the functional topics.

**There is no iNet X panel in this system.** The protocol reference calls
`0x0101` the panel because its system had one. Here the same address
identifies itself as `iNet X Interface AC` with device type INTERFACE — the
Aventa's own built-in BLE interface. The advertised name `Truma iNetX-<suffix>`
is Truma's name for that interface, not evidence of a separate box. Same
address, same role, different hardware.

### How to get this map at runtime — ask the broker

The addresses differ between systems, so they cannot be assumed. The app does
not guess either: before it asks anything about parameters, it asks the message
broker who is on the bus. This rides on its own control type (`0x02`), not on
the broker sub-protocol.

Request — 18 bytes, to `0x0000`:

```
00 00 01 05 0b 00 02 00 00 00 00 00 00 00 00 00  01 00
dest  src   size  ^ctrl                          ^request
```

Answer — from `0x0000`, CBOR body:

```
{"Devices": [0x0800, 0x0701, 0x0702, 0x0703, 0x032C, 0x0600, 0x0101,
             0x0200, 0x0400, 0x0801, 0x0904, 0x0500, 0x0601, 0x0501],
 "LastMessage": 1}
```

The app then sends `MBP/PARAM_DISCOVERY` to each device in turn, roughly one
per second. Never to the broadcast address: every device answers at once and
each answer wants its own acknowledgement, which buries the link.

Asking only `0x0101` returns interface parameters and nothing else — no
measured temperature, no fan level, no light state. Those live on `0x0801`,
and the only reliable way to learn that address is this list.

### Topics per device

| Device | Topics |
|---|---|
| `0x0101` interface | `RoomClimate`, `TimerConfig`, `Temperature`, `TimeAndDate`, `PowerMgmt`, `System`, `Install`, `Eol`, `ErrorReset`, `DeviceManagement` |
| `0x0801` appliance | `AirCooling`, `AirHeating`, `AirCirculation`, `AirDehumid`, `ACCAirCooling`, `ACCAirHeating`, `AmbientLight`, `LinePower`, `PowerMgmt`, `ErrorReset` |
| `0x0601` BLE peripheral | `BleDeviceManagement`, `DeviceManagement` |

`AirDehumid`, `ACCAirCooling` and `ACCAirHeating` appear in none of the prior
work — they are Aventa-specific and presumably carry the fan settings for the
dehumidifying and automatic modes.

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

## Framing: a notification is a message

Each notification on `fc314003` carries exactly one whole message. The length
the V3 header declares matches the notification to the byte, every time:

| notification | header size field | `16 + size - 9` |
|---|---|---|
| 248 B | `0x00F1` = 241 | 248 |
| 233 B | `0x00E2` = 226 | 233 |
| 221 B | `0x00D6` = 214 | 221 |
| 33 B  | `0x001A` = 26  | 33 |

The command channel announces each message's length beforehand (`83 <len16>`),
so the boundary is known before the data arrives.

**Never resynchronise byte by byte.** Frames carry no checksum, so a search for
the next header steps through a CBOR body and finds header-shaped bytes that
are not headers: two plausible addresses, a known control byte, a length that
fits. It latches onto one and then consumes every following message as that
phantom's payload. A single lost byte therefore silences the appliance for the
rest of the session — and silently, because a message eaten by a phantom frame
is indistinguishable from a message that never arrived.

This cost us an evening. Twenty-six parameter-discovery answers arrived intact
and not one became a state value; the log showed the bytes coming in and no
error anywhere. What made it visible was counting the bytes the framer discards
and logging how many frames each notification produced.

The rule that works: cut frames only at boundaries that can be real. A buffer
whose head cannot be a header is dropped whole, and a leftover still waiting
when a complete message arrives is discarded rather than glued to its front. A
truncated message then costs itself and nothing after it.

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

Our own captures confirm the appliance behaves this way. Across the four
traces it connected under three different addresses:

| Address | Kind | Occurrences |
|---|---|---|
| `FC:DE:C5:F0:A6:35` | public identity, resolved from a private address | 31 |
| `4C:1D:BB:C7:D8:8F` | random | 5 |
| `67:90:BE:21:D7:D0` | random | 4 |

The pairing exchange itself ran against one of the random addresses, and the
real identity appeared only inside it.

### It is the same endpoint, not a different one

Worth stating plainly, because the prior work is named after a panel: our
Aventa **is** an iNet X BLE endpoint. It advertises as `Truma iNetX-<suffix>`,
exposes the same characteristics, uses the same transport handshake and the
same TruMessageV3/CBOR messages, and our system contains a panel device at
`0x0101` that owns `RoomClimate` — whether that is a separate box or something
internal to the appliance makes no difference to the protocol.

So the difference between that project and this one is not how the connection
is made. It is which appliance sits behind it.

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
