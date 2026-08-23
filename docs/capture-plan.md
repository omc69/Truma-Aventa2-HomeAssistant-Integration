# Capture plan — Truma Aventa 2 over BLE

Read this before capturing. The Tempra work cost a whole evening of guessing
because four captures all came from the same battery and none covered the step
that mattered. This plan is built so the traces answer the open questions the
first time.

## What is already known

Most of the protocol is documented — see
[`truma-inetx-protocol-reference.md`](truma-inetx-protocol-reference.md),
reverse engineered by [daaaaan/truma-inetx-ble](https://github.com/daaaaan/truma-inetx-ble)
against a Combi D 4 E with an iNet X Panel. In short:

```
BLE GATT
  └─ UartPackage (8 bytes)      'S' + type + id + length
       └─ MuldexPackage (6 bytes)
            └─ TruMessageV3 (16 bytes)   dest / src / size / control type
                 └─ MBP (2 bytes)        message type + correlation id
                      └─ CBOR            {"tn": topic, "pn": parameter, "v": value}
```

Commands are CBOR triplets. Turning a room climate system off is literally
`{"tn": "RoomClimate", "pn": "Mode", "v": 0, "id": 0}`.

Relevant topics for an Aventa:

| Topic | Parameters | Covers |
|---|---|---|
| `RoomClimate` | `Mode`, `TgtTemp`, `Active` | on/off and the operating mode |
| `AirCooling` | `Active`, `TgtTemp`, `Temp`, `Mode` | cooling, comfort vs fast |
| `AirCirculation` | `Active`, `FanLevel` | fan, level 0–10 |
| `AmbientLight` | `Active`, `LightStep` | **the light**, on/off plus brightness |
| `Switches` | `Light1`–`Light6`, and more | further light circuits, if wired |
| `TimerConfig` | `Timer1`–`Timer6` | timers |

`RoomClimate.Mode`: 0 = off, 1 = ACC, 2 = cooling, 3 = heating, 4 = heating AC,
5 = venting, 6 = dehumidifying. Temperatures are tenths of a degree — 220 is
22.0 °C.

The protocol also already knows an Aventa: device address `0x0202`, named
`tinAventa`, and `DeviceTypeEnum` has `3 = AC`.

## What is genuinely open

The reference was written against a **Combi heater behind an iNet X Panel**.
Ours is an **Aventa 2 that the app talks to directly**. Four things need
confirming from your captures, and everything else follows from them:

1. **What the Aventa advertises.** The reference lists `FC310003` as
   "Interface AC" — plausible for us, but unconfirmed. The scan filter is
   `FC316029` and the manufacturer ID is 3187 (0x0C73).
2. **Which device address commands must go to.** For the Combi, `RoomClimate`
   goes to the panel (`0x0101`) but `AirHeating` goes to the heater (`0x0201`).
   Sending to the wrong address is silently ignored, so this must come from a
   capture, not a guess.
3. **The pairing exchange.** Truma uses a real BLE pairing with a 6-digit
   passkey, and the device remembers the client identity — reconnecting with a
   new one is rejected. This is the opposite of the Tempra, which refused
   pairing outright.
4. **Which topics your Aventa actually exposes**, and with which enum values.
   Parameter discovery returns the exact schema of *your* unit, including which
   modes are available and what the light is called.

## How to capture

Same tooling as the Tempra: **PacketLogger** on macOS with the iPhone attached,
then `File → Export → Text`. Export as text, not `.pklg`.

**Keep a written log** of wall-clock time and action while you capture — that is
what lets each command be matched to a byte sequence. A line per action is
enough:

```
17:04:12  App geöffnet
17:04:40  Verbunden
17:05:02  Klima EIN
17:05:20  Modus Kühlen
```

### Capture 1 — the important one: a cold start

Ideally **remove the pairing on the phone first** (Settings → Bluetooth →
forget), so the trace contains the pairing exchange.

1. Start the capture *before* opening the app.
2. Open the app, let it connect and pair, enter the passkey.
3. **Wait until the app has fully loaded** — all tiles populated. This part
   carries device discovery and parameter discovery, which is the complete
   schema of your unit and by far the most valuable single thing in the trace.
4. Stop the capture. Save as `traces/01-coldstart.txt`.

Do not do anything else in this one. It should be clean.

### Capture 2 — one action at a time

Leave **5 seconds between actions** and note each one. Separate captures per
group are fine and easier to read.

- Air conditioning **on**, then **off**
- Each **mode** in turn: cooling, venting, dehumidifying, automatic/ACC, and
  heating if your unit has it
- **Target temperature**: set it to two clearly different values, e.g. 18 °C
  and 26 °C — two points confirm the tenths-of-a-degree encoding
- **Fan**: step through every level, lowest to highest
- **Light on**, **light off**, and every brightness step if it has them
- Anything else the app offers — timers, sleep mode, whatever your unit shows

### Capture 3 — a reconnect

Close the app, reopen it, let it reconnect. This shows the shortened flow for a
device that is already paired, which is what the integration will do on every
poll.

## What to avoid

- **Do not** capture with the Home Assistant integration running alongside.
- Note whether an action is rejected or has no effect — a failed command in a
  trace is just as informative as a successful one, provided we know it failed.
- Do not trim the traces. The interesting part is often the handshake nobody
  thinks to keep.

## Then

Drop the exports in `traces/` and say so. `tools/decode_truma_trace.py` parses a
PacketLogger text export and prints the decoded CBOR for every message in it,
so the mapping from your action log to commands is mechanical rather than
guesswork.
