# Truma Aventa 2 — Home Assistant Integration (in progress)

Goal: control a **Truma Aventa 2** roof air conditioner from Home Assistant
over Bluetooth LE — on and off, operating modes, target temperature, fan level,
and the light.

Status: **capturing**. Nothing is implemented yet, but the first capture
already confirmed how to switch the unit and its light — see
[`docs/findings.md`](docs/findings.md).

## Where the protocol comes from

Truma's BLE protocol is largely documented already, by
[daaaaan/truma-inetx-ble](https://github.com/daaaaan/truma-inetx-ble), which
reverse engineered it against a Combi D 4 E behind an iNet X Panel. That
reference is mirrored here as
[`docs/truma-inetx-protocol-reference.md`](docs/truma-inetx-protocol-reference.md)
so this work has a stable copy.

It is not a finished answer for us. That work targets a heater reached through
a panel; ours is an Aventa the app talks to directly. What still has to come
out of our own captures is set out in
[`docs/capture-plan.md`](docs/capture-plan.md) — read that before capturing.

## What the first capture established

- Over BLE the payload **starts directly with the TruMessageV3 header**. The
  UartPackage and MuldexPackage layers the reference describes belong to the
  UART transport and are not present here.
- Our unit advertises as an iNetX device even though it is an Aventa with no
  separate panel.
- The air conditioner is device `0x0801`, identifying itself as
  `Aventa comfort 2. G`, type AC.
- **Routing differs per function**: `RoomClimate` commands go to the panel
  (`0x0101`), `AmbientLight` commands go to the Aventa (`0x0801`). A command
  sent to the wrong device is ignored without complaint.
- Switching on sends `RoomClimate.Mode = 1` — the automatic mode, not cooling.

The second capture, together with the enum definitions the unit reports about
itself, settled the whole control surface: modes, target temperature, fan
levels and the light. It also corrects the reference twice — the fan parameter
is Auto/Low/Mid/High/Night rather than Comfort/Fast, and the ventilating fan
range is 0–3 rather than 0–10. See [`docs/findings.md`](docs/findings.md).

Pairing turned out to be plain Bluetooth **Just Works** — the appliance
reports NoInputNoOutput and does not ask for MITM, so there is no PIN to enter
and BlueZ can complete it unattended. That was the last unknown; the
integration can be built.

## Tools

`tools/decode_truma_trace.py` reads a PacketLogger text export and prints the
decoded CBOR for every message, walking UartPackage → Muldex → TruMessageV3 →
MBP → CBOR:

```bash
pip install cbor2
python3 tools/decode_truma_trace.py traces/01-coldstart.txt
python3 tools/decode_truma_trace.py traces/*.txt --writes-only
```

`--writes-only` shows just the commands the app sent, which is what a control
action looks like on the wire. Handles differ between units, so the tool works
out which is the command channel and which are the data channels from the
traffic itself.

## Captures are not in this repository

`traces/` is deliberately ignored by git. A capture contains the unit's serial
number and the pairing identity the appliance remembers, which is closer to a
credential than to a device fact.

## Not affiliated

Not affiliated with, endorsed by, or supported by Truma. Use at your own risk.
