# The Bluetooth proxy

## Why it is mandatory here

The appliance advertises under a **rotating Resolvable Private Address** and
accepts an encrypted reconnect only from a client that can resolve that address
back to the stored bond. A phone's Bluetooth controller does this. **BlueZ does
not** — it can complete the pairing, but every later reconnect arrives on an
address it cannot map to the key, and the link is dropped.

Our own captures show the rotation directly. Across four traces the appliance
connected under three different addresses:

| Address | Kind | Occurrences |
|---|---|---|
| `FC:DE:C5:F0:A6:35` | public identity, resolved from a private address | 31 |
| `4C:1D:BB:C7:D8:8F` | random | 5 |
| `67:90:BE:21:D7:D0` | random | 4 |

That this defeats BlueZ specifically was established by
[rpodgorny/hass-truma-inetx](https://github.com/rpodgorny/hass-truma-inetx),
exhaustively — IRK stored, LL-Privacy enabled, three different adapters,
failing at the controller level in every combination.

**ESP-IDF resolves private addresses in the controller**, the way a phone does.
That is the whole reason a proxy fixes this, and also why the framework matters
more than the board.

## Choosing a board

Any **ESP32**, **ESP32-C3** or **ESP32-S3**. Two to avoid, easy to buy by
mistake: an **ESP32-S2** has no Bluetooth at all, and neither does anything
based on **ESP8266**.

Placement decides the rest:

- **In sight of the appliance** — any cheap board does. An M5Stack Atom Lite is
  a convenient one: ESP32, USB-C, cased.
- **Inside a metal enclosure** — take a board with an external antenna
  connector, an ESP32-WROOM-32**U** with a U.FL pigtail, and route the antenna
  out. Otherwise the proxy's own Wi-Fi becomes the next thing to fail.
- **Wired network available** — an Olimex ESP32-POE-ISO takes power and network
  over one cable and removes Wi-Fi from the equation.

Put it within a few metres of the appliance. Distance shows up as connect
failures rather than as a clean error.

## Configuration

Two settings carry the whole thing, and both are easy to miss:

```yaml
esphome:
  name: truma-proxy
  friendly_name: Truma Bluetooth Proxy

esp32:
  board: esp32dev          # m5stack-atom for an Atom Lite, esp32-c3-devkitm-1 for a C3
  framework:
    type: esp-idf          # REQUIRED — an Arduino build does not resolve
                           # private addresses in the controller

logger:
api:
  encryption:
    key: !secret api_encryption_key
ota:
  - platform: esphome
    password: !secret ota_password

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
  ap:
    ssid: "Truma Proxy Fallback"

esp32_ble_tracker:
  scan_parameters:
    interval: 1100ms
    window: 1100ms
    active: true

bluetooth_proxy:
  active: true             # REQUIRED — without it the proxy only relays
                           # advertisements and cannot open a connection
```

`active: true` is what separates a proxy that works from one that behaves like
a Shelly BLU Gateway: relaying advertisements, unable to connect.

Flash it, and Home Assistant discovers the proxy through the ESPHome
integration on its own.

## Checking it took over

The integration raises a repair issue while the appliance is only reachable
through the host's own adapter, and clears it once a proxy can reach it. So the
short answer is: the warning under **Settings → System → Repairs** disappears.

For the longer answer, enable debug logging:

```yaml
logger:
  logs:
    custom_components.truma_aventa: debug
    habluetooth.wrappers: debug
```

and look for the connection-path line. It should list the proxy, scoring better
than the host adapter:

```
Found 2 connection path(s), preferred order: truma-proxy (RSSI=-46) ..., hci0 (RSSI=-85) ...
```

Home Assistant picks the better path by itself; nothing in the integration
needs configuring.

## One proxy can serve more than this

A Bluetooth proxy is not per-integration. The same ESP32 improves every BLE
device in range — so if you also run something like a battery monitor over BLE
in the same vehicle, one well-placed proxy covers both. An ESP32 proxy supports
three concurrent connections.
