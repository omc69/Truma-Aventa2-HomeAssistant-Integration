"""The identity this client presents to the appliance.

The appliance keeps a list of clients and expects each to announce itself as
ordinary topic data after registering. Captures show the app sending its
MobileIdentity before the appliance reports anything, and the identity is what
the unit remembers -- so it has to be generated once and then reused, not made
up afresh on every connection.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

CONF_IDENTITY = "identity"

#: Shown in the appliance's own list of paired clients.
DEFAULT_USER_NAME = "Home Assistant"


def new_identity(user_name: str = DEFAULT_USER_NAME) -> dict[str, str]:
    """Create an identity for this Home Assistant instance.

    Two separate ids, matching what the app sends. A second phone seen in the
    captures carried the same Uuid as the first but a different Muid, so the
    Uuid identifies the application and the Muid the individual client. Their
    letter case differs in every capture and is reproduced here.
    """
    return {
        "muid": str(uuid4()).upper(),
        "uuid": str(uuid4()).lower(),
        "name": user_name,
    }


def identity_parameters(identity: dict[str, Any]) -> list[tuple[str, str]]:
    """The MobileIdentity parameters to announce, in the order the app uses."""
    return [
        ("UserName", identity["name"]),
        ("Muid", identity["muid"]),
        ("Uuid", identity["uuid"]),
    ]
