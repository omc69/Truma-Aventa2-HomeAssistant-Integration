"""Connection manager for a Truma appliance over BLE.

Owns one link: connect, register, subscribe to the topics we care about, then
stay connected and translate inbound topic updates into state. Unlike a
battery BMS this appliance serves several clients at once and pushes changes
on its own, so there is nothing to poll -- the connection is held open and
updates arrive as they happen.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from bleak import BleakError
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import (
    ACK_DATA,
    ADDR_APPLIANCE,
    ADDR_BROADCAST,
    ADDR_INTERFACE,
    ADDR_MESSAGE_BROKER,
    ADDR_UNREGISTERED,
    CMD_CHAR_UUID,
    CONFIRM_MSG_ACK,
    CONTROL_DISCOVERY,
    CONTROL_REGISTRATION,
    DATA_READ_CHAR_UUID,
    DATA_WRITE_CHAR_UUID,
    DEVICE_DISCOVERY_REQUEST,
    DEVICE_DISCOVERY_TIMEOUT,
    DEVICE_GAP,
    DISCOVERY_GAP,
    IDENTITY_GAP,
    MAX_TOPICS_PER_SUBSCRIBE,
    MBP_INFO,
    MBP_PARAM_DISCOVERY,
    MBP_PARAM_DISCOVERY_RESPONSE,
    MBP_SUBSCRIBE,
    MBP_WRITE,
    OP_INIT_DATA_TRANSFER,
    OP_MSG_ACK,
    OP_READY_STATUS,
    PROTOCOL_VERSION,
    SUBSCRIBE_GAP,
    SUBSCRIBE_SETTLE,
    SUBSCRIBED_TOPICS,
    TOPIC_AIR_CIRCULATION,
    TOPIC_AIR_COOLING,
    TOPIC_AIR_DEHUMID,
    TOPIC_AIR_HEATING,
    TOPIC_AMBIENT_LIGHT,
    TOPIC_IDENTIFY,
    TOPIC_MOBILE_IDENTITY,
    TOPIC_ROOM_CLIMATE,
)
from .frames import Frame, FrameStream, build, build_mbp
from .identity import identity_parameters
from .models import TrumaState

_LOGGER = logging.getLogger(__name__)

#: How long to wait for each step of the transport handshake.
_READY_TIMEOUT = 5.0
#: How long to wait for the appliance to accept our registration.
_REGISTER_TIMEOUT = 10.0
#: Reconnect backoff bounds, seconds.
_BACKOFF_START = 5.0
_BACKOFF_MAX = 120.0
#: Conservative default until the negotiated MTU is known.
_DEFAULT_CHUNK = 180

#: Which parameter of which topic maps to which state field.
_FIELD_MAP: dict[tuple[str, str], str] = {
    (TOPIC_ROOM_CLIMATE, "Mode"): "mode",
    (TOPIC_ROOM_CLIMATE, "TgtTemp"): "target_temperature",
    (TOPIC_AIR_COOLING, "Mode"): "cooling_fan_mode",
    (TOPIC_AIR_COOLING, "Temp"): "current_temperature",
    (TOPIC_AIR_HEATING, "Mode"): "heating_fan_mode",
    (TOPIC_AIR_CIRCULATION, "FanLevel"): "fan_level",
    (TOPIC_AMBIENT_LIGHT, "Active"): "light_on",
    (TOPIC_AMBIENT_LIGHT, "LightStep"): "light_step",
    (TOPIC_IDENTIFY, "Name"): "name",
    (TOPIC_IDENTIFY, "SerialNr"): "serial_number",
}

#: Topics the appliance owns rather than the panel. Commands for these go to
#: the appliance's own address, which is learned at runtime; commands for
#: RoomClimate go to the panel. Sending to the wrong one is ignored silently.
_APPLIANCE_TOPICS = frozenset(
    {
        TOPIC_AIR_COOLING,
        TOPIC_AIR_HEATING,
        TOPIC_AIR_CIRCULATION,
        TOPIC_AIR_DEHUMID,
        TOPIC_AMBIENT_LIGHT,
    }
)


class TrumaBleDevice:
    """Maintains a live connection to one Truma appliance."""

    def __init__(
        self,
        ble_device: BLEDevice,
        *,
        identity: dict[str, str],
        name: str | None = None,
    ) -> None:
        """Initialise the manager."""
        self._identity = identity
        self._ble_device = ble_device
        self._name = name or ble_device.name or ble_device.address
        self._listeners: list[Callable[[TrumaState], None]] = []

        self._client: BleakClientWithServiceCache | None = None
        self._stream = FrameStream()
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._wake = asyncio.Event()

        self._ready = asyncio.Event()
        self._registered = asyncio.Event()
        self._devices: tuple[int, ...] = ()
        self._devices_listed = asyncio.Event()
        self._send_lock = asyncio.Lock()
        #: Command-channel writes are queued and issued by a single task.
        #: Parameter discovery makes the appliance send dozens of messages a
        #: second, each wanting its own confirmation, and firing a task per
        #: message put that many concurrent writes on one characteristic.
        self._commands: asyncio.Queue[bytes] = asyncio.Queue(maxsize=256)
        self._writer: asyncio.Task[None] | None = None

        #: Address the appliance assigns us during registration.
        self._address: int = ADDR_UNREGISTERED
        #: Address of the appliance itself, learned from its own messages.
        self._appliance: int | None = None
        self._chunk = _DEFAULT_CHUNK

        self.state = TrumaState()

    # -- public API ---------------------------------------------------------

    @property
    def address(self) -> str:
        """Bluetooth address."""
        return self._ble_device.address

    @property
    def name(self) -> str:
        """Advertised name."""
        return self._name

    @property
    def connected(self) -> bool:
        """Whether a registered, usable link exists."""
        return (
            self._client is not None
            and self._client.is_connected
            and self._registered.is_set()
        )

    def add_listener(
        self, listener: Callable[[TrumaState], None]
    ) -> Callable[[], None]:
        """Register a state callback. Returns a callable that removes it."""
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        """Adopt a fresher BLEDevice."""
        self._ble_device = ble_device

    async def async_start(self) -> None:
        """Start connecting and stay connected."""
        if self._task is not None:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name=f"truma-{self.address}")

    async def async_stop(self) -> None:
        """Disconnect and stop reconnecting."""
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._async_disconnect()

    async def async_set_parameter(self, topic: str, parameter: str, value: Any) -> None:
        """Write one parameter, routed to whichever device owns the topic."""
        if not self.connected:
            raise BleakError(f"{self._name}: not connected")
        dest = self._destination_for(topic)
        _LOGGER.debug("%s: -> %s.%s = %r (dest 0x%04X)", self._name, topic, parameter, value, dest)
        await self._async_send(
            build_mbp(
                dest=dest,
                src=self._address,
                mbp_type=MBP_WRITE,
                body={"tn": topic, "pn": parameter, "v": value},
            )
        )

    # -- connection ---------------------------------------------------------

    async def _run(self) -> None:
        backoff = _BACKOFF_START
        while not self._stopping:
            try:
                await self._async_connect_and_hold()
            except asyncio.CancelledError:
                raise
            except (BleakError, TimeoutError, OSError) as err:
                _LOGGER.debug("%s: connection lost: %s", self._name, err)
            except Exception:
                _LOGGER.exception("%s: unexpected error", self._name)
            else:
                backoff = _BACKOFF_START

            await self._async_disconnect()
            self._notify()
            if self._stopping:
                break
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)

    async def _async_connect_and_hold(self) -> None:
        self._stream.reset()
        self._registered.clear()
        self._devices = ()
        self._devices_listed.clear()
        self._address = ADDR_UNREGISTERED
        self._appliance = None

        _LOGGER.debug("%s: connecting to %s", self._name, self.address)
        client = await establish_connection(
            BleakClientWithServiceCache,
            self._ble_device,
            self._name,
            disconnected_callback=self._on_disconnected,
            ble_device_callback=lambda: self._ble_device,
            use_services_cache=True,
        )
        self._client = client
        if mtu := getattr(client, "mtu_size", 0):
            self._chunk = max(20, mtu - 3)

        # Never subscribe to the alternate command characteristic: doing so
        # breaks the transport.
        while not self._commands.empty():
            self._commands.get_nowait()
        self._writer = asyncio.create_task(self._run_writer())

        await client.start_notify(CMD_CHAR_UUID, self._on_command)
        await client.start_notify(DATA_READ_CHAR_UUID, self._on_data)

        await self._async_register()
        _LOGGER.debug("%s: registered as 0x%04X", self._name, self._address)
        await self._async_subscribe()
        await self._async_announce_identity()
        await self._async_discover_parameters(*await self._async_list_devices())

        # Stay connected. The appliance pushes updates by itself; the constant
        # acknowledgement traffic keeps the link alive, so no keepalive of our
        # own is needed.
        while not self._stopping and client.is_connected:
            await asyncio.sleep(1.0)

    async def _async_disconnect(self) -> None:
        if self._writer is not None:
            self._writer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._writer
            self._writer = None
        client, self._client = self._client, None
        self._registered.clear()
        if client is None:
            return
        with contextlib.suppress(BleakError, TimeoutError, OSError):
            await client.disconnect()

    # -- protocol -----------------------------------------------------------

    async def _async_register(self) -> None:
        """Announce ourselves and learn the address we are given."""
        await self._async_send(
            build(
                dest=ADDR_MESSAGE_BROKER,
                src=ADDR_UNREGISTERED,
                control=CONTROL_REGISTRATION,
                payload=bytes([0x01, 0x00]) + _cbor({"pv": PROTOCOL_VERSION}),
            )
        )
        try:
            await asyncio.wait_for(self._registered.wait(), timeout=_REGISTER_TIMEOUT)
        except TimeoutError as err:
            raise BleakError(f"{self._name}: registration was not answered") from err

    async def _async_subscribe(self) -> None:
        """Subscribe to the topics we follow, in the batches the app uses."""
        topics = list(SUBSCRIBED_TOPICS)
        for start in range(0, len(topics), MAX_TOPICS_PER_SUBSCRIBE):
            batch = topics[start : start + MAX_TOPICS_PER_SUBSCRIBE]
            await self._async_send(
                build_mbp(
                    dest=ADDR_MESSAGE_BROKER,
                    src=self._address,
                    mbp_type=MBP_SUBSCRIBE,
                    body={"tn": batch},
                )
            )
            await asyncio.sleep(SUBSCRIBE_GAP)
        # The appliance needs a moment to work through a subscription; a
        # parameter discovery sent on top of one goes unanswered.
        await asyncio.sleep(SUBSCRIBE_SETTLE)

    async def _async_announce_identity(self) -> None:
        """Tell the appliance who we are.

        The appliance keeps a list of clients and expects each to announce
        itself as ordinary topic data. In the captures the app does this before
        the appliance reports anything at all, so it is not decoration.
        """
        for parameter, value in identity_parameters(self._identity):
            await self._async_send(
                build_mbp(
                    dest=ADDR_BROADCAST,
                    src=self._address,
                    mbp_type=MBP_INFO,
                    body={"tn": TOPIC_MOBILE_IDENTITY, "pn": parameter, "v": value},
                )
            )
            await asyncio.sleep(IDENTITY_GAP)

    async def _async_list_devices(self) -> tuple[int, ...]:
        """Ask the broker which devices are on the bus.

        Which address the air conditioning answers on differs between systems
        -- the protocol reference names 0x0201, this one uses 0x0801 -- so
        guessing costs the appliance's own parameters, which is everything a
        climate entity needs. The app asks and then queries each device it is
        told about, and so do we. Our own address is left out: we would only
        be asking ourselves.
        """
        await self._async_send(
            build(
                dest=ADDR_MESSAGE_BROKER,
                src=self._address,
                control=CONTROL_DISCOVERY,
                payload=bytes([DEVICE_DISCOVERY_REQUEST, 0x00]),
            )
        )
        try:
            await asyncio.wait_for(
                self._devices_listed.wait(), timeout=DEVICE_DISCOVERY_TIMEOUT
            )
        except TimeoutError:
            _LOGGER.debug(
                "%s: no device list; asking the interface alone", self._name
            )
            return (ADDR_INTERFACE,)
        devices = tuple(
            address
            for address in self._devices
            if address not in (self._address, ADDR_MESSAGE_BROKER)
        )
        _LOGGER.debug(
            "%s: bus holds %s",
            self._name,
            ", ".join(f"0x{address:04X}" for address in devices),
        )
        return devices or (ADDR_INTERFACE,)

    async def _async_discover_parameters(self, *targets: int) -> None:
        """Ask devices to report every parameter they have.

        Subscribing only brings changes, and an appliance sitting idle has
        none — so without this the entities stay empty until someone touches a
        control. Parameter discovery is what the app uses to fill its screen on
        connect, and it returns the current value of everything at once.
        """
        # Deliberately never ADDR_BROADCAST: asking every device for every
        # parameter at once buries the link in messages that each need their
        # own confirmation. The app addresses devices individually too.
        chosen = targets or (ADDR_APPLIANCE, ADDR_INTERFACE)
        gap = DEVICE_GAP if len(chosen) > 2 else DISCOVERY_GAP
        for target in chosen:
            _LOGGER.debug("%s: parameter discovery -> 0x%04X", self._name, target)
            await self._async_send(
                build_mbp(
                    dest=target,
                    src=self._address,
                    mbp_type=MBP_PARAM_DISCOVERY,
                )
            )
            await asyncio.sleep(gap)

    def _destination_for(self, topic: str) -> int:
        """Which device owns a topic.

        RoomClimate belongs to the interface, everything else to the appliance
        itself, whose address is learned at runtime. Falling back to the
        interface is safe: it is the address that exists on every system.
        """
        if topic in _APPLIANCE_TOPICS and self._appliance is not None:
            return self._appliance
        return ADDR_INTERFACE

    async def _async_send(self, frame: bytes) -> None:
        """Send one frame through the transport handshake.

        The appliance will not accept data until it has said it is ready, and
        the exchange is not re-entrant, so sends are serialised.
        """
        client = self._client
        if client is None:
            raise BleakError(f"{self._name}: not connected")

        async with self._send_lock:
            _LOGGER.debug(
                "%s: -> %d bytes to 0x%04X",
                self._name,
                len(frame),
                int.from_bytes(frame[0:2], "little"),
            )
            self._ready.clear()
            await client.write_gatt_char(
                CMD_CHAR_UUID,
                bytes([OP_INIT_DATA_TRANSFER]) + len(frame).to_bytes(2, "little"),
                response=False,
            )
            try:
                await asyncio.wait_for(self._ready.wait(), timeout=_READY_TIMEOUT)
            except TimeoutError as err:
                raise BleakError(f"{self._name}: appliance never signalled ready") from err

            for offset in range(0, len(frame), self._chunk):
                await client.write_gatt_char(
                    DATA_WRITE_CHAR_UUID,
                    frame[offset : offset + self._chunk],
                    response=False,
                )

    # -- callbacks ----------------------------------------------------------

    def _on_disconnected(self, _client: BleakClientWithServiceCache) -> None:
        _LOGGER.debug("%s: disconnected", self._name)
        self._registered.clear()
        self._wake.set()

    def _on_command(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Drive the transport state machine."""
        raw = bytes(data)
        _LOGGER.debug("%s: <- CMD %s", self._name, raw.hex(" "))
        if not raw:
            return
        if raw[0] == OP_READY_STATUS:
            self._ready.set()
        elif raw[0] == OP_MSG_ACK:
            # Arrives asynchronously; confirm it without blocking anything.
            self._schedule_command(CONFIRM_MSG_ACK)

    def _on_data(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Consume inbound messages."""
        raw = bytes(data)
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "%s: <- DATA %d bytes %s", self._name, len(raw), raw[:32].hex(" ")
            )
        if raw:
            # Acknowledge every inbound notification, which is what the app
            # does. Acknowledging only completed messages instead made the
            # appliance answer f0 04 -- AckDataTransfer with TIMEOUT_ON_SEND --
            # every five seconds: it was waiting for an acknowledgement that
            # never came. The resulting steady traffic is also what keeps the
            # link alive, so no keepalive of our own is needed.
            self._schedule_command(ACK_DATA)
        before = self._stream.dropped
        frames = self._stream.feed(raw)
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "%s: framer: %d frame(s), %d byte(s) buffered, %d discarded",
                self._name,
                len(frames),
                self._stream.pending,
                self._stream.dropped - before,
            )
        changed: dict[str, Any] = {}
        for frame in frames:
            try:
                changed.update(self._handle_frame(frame))
            except Exception:
                # bleak swallows anything raised in a notification callback, so
                # a decoding fault is indistinguishable from a silent
                # appliance unless it is logged here.
                _LOGGER.exception(
                    "%s: could not handle a frame from 0x%04X",
                    self._name,
                    frame.src,
                )
        if changed:
            self.state = self.state.with_values(changed)
            _LOGGER.debug("%s: state changed: %s", self._name, sorted(changed))
            self._notify()

    def _schedule_command(self, payload: bytes) -> None:
        """Queue a command-channel write from a notification callback."""
        try:
            self._commands.put_nowait(payload)
        except asyncio.QueueFull:
            # Dropping an acknowledgement is better than growing without
            # bound; the appliance repeats anything it did not hear.
            _LOGGER.debug("%s: command queue full, dropping an ack", self._name)

    async def _run_writer(self) -> None:
        """Issue queued command-channel writes one at a time."""
        while True:
            payload = await self._commands.get()
            client = self._client
            if client is None:
                continue
            with contextlib.suppress(BleakError, TimeoutError, OSError):
                await client.write_gatt_char(CMD_CHAR_UUID, payload, response=False)

    def _handle_frame(self, frame: Frame) -> dict[str, Any]:
        """Turn one inbound frame into state changes."""
        if frame.control == CONTROL_REGISTRATION:
            body = frame.body
            if isinstance(body, dict) and "addr" in body:
                self._address = int(body["addr"])
                self._registered.set()
            return {}

        if frame.control == CONTROL_DISCOVERY:
            body = frame.body
            if isinstance(body, dict) and "Devices" in body:
                self._devices = tuple(
                    int(address) for address in body["Devices"] or ()
                )
                self._devices_listed.set()
            return {}

        if frame.mbp_type not in (MBP_INFO, MBP_PARAM_DISCOVERY_RESPONSE):
            return {}

        body = frame.body
        if not isinstance(body, dict):
            return {}

        changed: dict[str, Any] = {}
        raw = dict(self.state.raw)
        seen = 0
        for topic, parameter, value in _walk_parameters(body):
            seen += 1
            # Keyed by the device that reported it: several devices on the bus
            # carry the same topic, and a bare "Topic.Parameter" lets the
            # interface's copy overwrite the appliance's.
            raw[f"{frame.src:04X}/{topic}.{parameter}"] = value
            # The appliance identifies itself by owning these topics; its
            # address is not fixed and is not the one the reference lists.
            if (
                topic in _APPLIANCE_TOPICS
                and frame.src not in (0, ADDR_INTERFACE)
                and self._appliance != frame.src
            ):
                self._appliance = frame.src
                self._schedule_discovery(frame.src)
            if (field := _FIELD_MAP.get((topic, parameter))) is not None:
                changed[field] = value
        if raw != self.state.raw:
            changed["raw"] = raw
        if "LastMessage" in body:
            changed["complete"] = self.state.complete | {f"{frame.src:04X}"}
        if "LastMessage" in body and _LOGGER.isEnabledFor(logging.DEBUG):
            # The sentinel ends a discovery burst, which is the one moment the
            # full inventory of what this appliance reports is known.
            _LOGGER.debug(
                "%s: 0x%04X reported %d parameter(s): %s",
                self._name,
                frame.src,
                len(raw),
                ", ".join(f"{key}={raw[key]!r}" for key in sorted(raw)),
            )
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "%s: 0x%04X mbp 0x%02X carried %d parameter(s); body keys %s",
                self._name,
                frame.src,
                frame.mbp_type or 0,
                seen,
                sorted(body),
            )
        return changed

    def _schedule_discovery(self, target: int) -> None:
        """Ask a newly identified device for its parameters, off the callback."""

        async def _run() -> None:
            with contextlib.suppress(BleakError, TimeoutError, OSError):
                await self._async_discover_parameters(target)

        asyncio.get_running_loop().create_task(_run())

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener(self.state)


def _cbor(value: Any) -> bytes:
    import cbor2

    return cbor2.dumps(value)


def _walk_parameters(body: dict[str, Any]):
    """Yield (topic, parameter, value) from either message shape.

    An INFO message carries a single triplet; a parameter-discovery response
    nests them under topics, each with a list of parameters.
    """
    if isinstance(body.get("tn"), str) and "pn" in body:
        yield body["tn"], body["pn"], body.get("v")
        return
    for topic in body.get("topics", []) or []:
        if not isinstance(topic, dict):
            continue
        for parameter in topic.get("parameters", []) or []:
            if not isinstance(parameter, dict):
                continue
            name = parameter.get("tn") or topic.get("tn")
            if isinstance(name, str) and "pn" in parameter:
                yield name, parameter["pn"], parameter.get("v")
