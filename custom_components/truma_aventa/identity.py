"""Re-exported for the Home Assistant layer.

The identity is protocol knowledge -- what the appliance expects a client to
announce about itself -- so it lives with the protocol. Home Assistant only
needs to generate one and keep it.
"""

from __future__ import annotations

from .truma_ble.identity import (
    CONF_IDENTITY,
    DEFAULT_USER_NAME,
    identity_parameters,
    new_identity,
)

__all__ = [
    "CONF_IDENTITY",
    "DEFAULT_USER_NAME",
    "identity_parameters",
    "new_identity",
]
