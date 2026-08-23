<img src="icon.png" width="96" align="right" alt="Truma">

# Truma Aventa — Home Assistant Integration

[![hacs](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz)
[![release](https://img.shields.io/github/v/release/omc69/Truma-Aventa2-HomeAssistant-Integration)](https://github.com/omc69/Truma-Aventa2-HomeAssistant-Integration/releases)
[![validate](https://github.com/omc69/Truma-Aventa2-HomeAssistant-Integration/actions/workflows/validate.yml/badge.svg)](https://github.com/omc69/Truma-Aventa2-HomeAssistant-Integration/actions/workflows/validate.yml)

Controls a **Truma Aventa** roof air conditioner from Home Assistant over
Bluetooth LE — no cloud, no iNet X Connect module, no MQTT broker.

Developed against an **Aventa comfort 2nd generation**. It should suit other
appliances speaking Truma's iNet X BLE protocol, but only that one has been
tested.

## Entities

**Climate**

| | |
|---|---|
| Modes | Off, Auto, Cool, Heat/Cool, Fan only, Dry |
| Target temperature | 16–30 °C |
| Current temperature | as the appliance measures it |
| Fan | Auto, Low, Mid, High, Night |
| Action | what the appliance is *doing*: cooling, heating, drying, fan, idle |

The modes are the ones the appliance reports about itself. Plain heating is
absent on purpose: an Aventa heats through the heat pump, which is the
Heat/Cool mode.

**Light** — the ambient light, on/off with brightness.

**Binary sensor** — a diagnostic *Connection*, which stays available when
everything else goes away. A link that keeps flapping is the signature of a
missing proxy, and that is only visible if something reports the link itself.

**Sensors — every parameter the bus reports.** The appliance answers parameter
discovery with everything it knows about itself: 88 values on the air
conditioning alone, from measured temperatures and mains presence to error
codes, firmware revisions and timer configuration. Each becomes a diagnostic
sensor, grouped under the device that reported it.

A Truma system answers on more addresses than it has devices — the interface
here answers on three, all reporting the same parameters under one
`Identify.UniqueID`. Addresses that share an identity are folded into one Home
Assistant device, so the list stays readable.

Writing stays with the climate and light entities. Parameter discovery exposes
`System.FactoryReset` and `DeviceManagement.Delete` alongside everything else,
and a generic writable entity over that surface would be a foot-gun.

Values are **pushed**: once subscribed, the appliance reports changes as they
happen, including changes made at the panel or from the app.

## Installation

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=omc69&repository=Truma-Aventa2-HomeAssistant-Integration&category=integration)

Then **Download**, and restart Home Assistant.

## An ESP32 Bluetooth proxy is required

Not a preference. The appliance advertises under a **fast-rotating Resolvable
Private Address** and only accepts an encrypted reconnect from a client that
can resolve that address back to the stored bond. A phone's controller does
this. **BlueZ does not** — it can pair the appliance, but every later reconnect
arrives on an address it cannot map to the key, and the link is dropped.

This was established independently and exhaustively by
[rpodgorny/hass-truma-inetx](https://github.com/rpodgorny/hass-truma-inetx)
against the same protocol — IRK stored, LL-Privacy enabled, three different
adapters — and it fails at the controller level regardless.

ESP-IDF resolves private addresses in the controller the way a phone does, so
an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html)
works where the host adapter cannot. Stock proxy firmware is enough:

```yaml
esp32:
  framework:
    type: esp-idf   # required — Arduino builds do not resolve RPAs in-controller

bluetooth_proxy:
  active: true
```

Put the proxy within a few metres of the appliance. Distance shows up as
connect failures rather than as a clean error.

[`docs/bluetooth-proxy.md`](docs/bluetooth-proxy.md) has a complete
configuration, notes on choosing a board, and how to confirm the proxy has
taken over.

While the appliance is only reachable through the host's own adapter, the
integration raises a repair issue explaining it — so a link that keeps dropping
is not left looking like a bug.

## Pairing

**The integration pairs for you** — but the order matters and cannot be worked
around:

1. Add the integration and pick the appliance.
2. Setup then asks you to **start pairing at the unit itself**.
3. Do that, then continue in Home Assistant.

The appliance accepts a new client only while its pairing state is active, and
that state lasts a short while — so it has to be started *before* the step
runs, not after it has already failed. Setup stays on that step if pairing is
refused, so you can start it again and retry without beginning over.

Pairing needs **no PIN**. The appliance reports itself as *NoInputNoOutput* and
does not request MITM protection, so this is Bluetooth **Just Works** — decoded
from the Security Manager exchange in our own capture, which also contradicts
the six-digit passkey the protocol reference mentions.

What you do have to do is put the appliance into its pairing state first. It
refuses new clients otherwise, and it has a limited number of client slots — if
setup reports that it could not pair, start pairing on the unit or remove a
device you no longer use in the Truma app, then try again. A refusal followed
by a successful retry two minutes later is exactly what our captures show.

Bonding matters more than it first appears. Without it the appliance is not
merely unusable: it is **undiscoverable**. Each rotation of its private address
looks like a separate short-lived device, so nothing accumulates into something
you can select. With a bond, the host resolves those addresses back to one
identity.

## Requirements

- Home Assistant 2025.2 or newer with the `bluetooth` integration
- An **ESPHome Bluetooth proxy** on an `esp-idf` build, near the appliance —
  see above. The host's own adapter is not sufficient. Passive-only gateways
  such as a Shelly BLU Gateway relay advertisements but cannot open a
  connection at all.

## How it works

Truma's BLE protocol is layered: a transport handshake on one characteristic,
messages on two others, and inside them a `TruMessageV3` header wrapping CBOR
topic/parameter/value triplets. Turning the unit off is literally
`{"tn": "RoomClimate", "pn": "Mode", "v": 0}`.

Two things are easy to get wrong and are worth knowing:

- **Routing differs per function.** `RoomClimate` belongs to the appliance's
  BLE interface; `AmbientLight`, `AirCooling`, `AirHeating`, `AirCirculation`
  and `AirDehumid` belong to the appliance itself, whose address is not fixed
  and is learned at runtime. A command sent to the wrong device is ignored
  without any error.

  No separate iNet X panel is needed. On an Aventa the interface is built in —
  it identifies itself as `iNet X Interface AC`, which is also why the unit
  advertises as `Truma iNetX-…`.
- **The fan lives in three places.** Cooling and heating each carry their own
  fan parameter, and while ventilating it is `AirCirculation.FanLevel`. The
  integration writes whichever matches the running mode.

Full protocol notes, including where our findings correct the reference this
work builds on, are in [`docs/findings.md`](docs/findings.md).

## Credits

The protocol groundwork comes from
[daaaaan/truma-inetx-ble](https://github.com/daaaaan/truma-inetx-ble), which
documented it against a Combi heater behind an iNet X panel. That reference is
mirrored in [`docs/`](docs/truma-inetx-protocol-reference.md).

The finding that a host Bluetooth adapter cannot maintain the link, and that an
esp-idf Bluetooth proxy can, comes from
[rpodgorny/hass-truma-inetx](https://github.com/rpodgorny/hass-truma-inetx) —
a mature integration for an iNet X panel driving a Combi heater, with heating,
water heating, energy sources and a custom dashboard card. If that is your
setup, use theirs. This one exists because an Aventa is a different appliance:
it needs cooling, dehumidifying and heat-pump heating, plus the ambient light,
none of which a Combi has. No code is shared; that project is GPL-3.0 and this
one is MIT.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest tests/ -q
```

Every byte sequence in the tests comes from a real capture of the appliance,
paired with what the app was doing at that moment.

`tools/decode_truma_trace.py` decodes a PacketLogger text export into readable
messages — useful for adding support for a model that behaves differently.

## Not affiliated

Not affiliated with, endorsed by, or supported by Truma. "Truma" and the Truma
logo are trademarks of their respective owners, used here only to identify the
compatible hardware. Use at your own risk.

## License

MIT — see [LICENSE](LICENSE).
