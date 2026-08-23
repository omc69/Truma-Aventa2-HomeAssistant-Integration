"""Bonding the appliance from inside Home Assistant.

Pairing is Just Works — the appliance reports NoInputNoOutput and does not ask
for MITM protection — so there is nothing for a user to type. What there is,
is a reason not to send them to a terminal: without a bond the appliance is
not merely unusable, it is undiscoverable, because every rotation of its
private address looks like a separate short-lived device.
"""

from __future__ import annotations

import contextlib
import logging

from bleak import BleakError
from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .truma_ble.const import CMD_CHAR_UUID

_LOGGER = logging.getLogger(__name__)


def _discard(_sender: object, _data: bytearray) -> None:
    """Ignore notifications during the bond check."""


async def async_pair(ble_device: BLEDevice) -> bool:
    """Bond with the appliance. True when the link is usable afterwards.

    Connecting and pairing suffices on both transports that matter: BlueZ
    completes Just Works through its default agent, and a Bluetooth proxy does
    the same inside its own controller.
    """
    client = await establish_connection(
        BleakClientWithServiceCache,
        ble_device,
        ble_device.address,
        use_services_cache=False,
    )
    try:
        try:
            await client.pair()
        except NotImplementedError:
            # Some backends cannot pair explicitly but will have bonded
            # implicitly the moment an encrypted characteristic was touched.
            _LOGGER.debug("%s: backend cannot pair explicitly", ble_device.address)
        except BleakError as err:
            _LOGGER.debug("%s: pair() refused: %s", ble_device.address, err)

        # Whether the bond took is not something to take on trust. Subscribing
        # is exactly what the integration does next, and it needs the encrypted
        # link, so it is the honest test.
        try:
            await client.start_notify(CMD_CHAR_UUID, _discard)
            await client.stop_notify(CMD_CHAR_UUID)
        except BleakError as err:
            _LOGGER.debug(
                "%s: the command channel stayed shut after pairing: %s",
                ble_device.address,
                err,
            )
            return False
        return True
    finally:
        # A failure disconnecting must not mask the result.
        with contextlib.suppress(BleakError, TimeoutError, OSError):
            await client.disconnect()
