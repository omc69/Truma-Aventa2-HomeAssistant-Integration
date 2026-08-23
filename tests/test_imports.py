"""Guards against the integration failing to import at all.

A name that the Home Assistant modules import from the protocol package but
that the package does not export raises ImportError at load time. Home
Assistant reports that as "Invalid handler specified" when someone tries to
add the integration — a message that says nothing about the real cause, and
which no other test here would catch, because the protocol layer itself is
perfectly healthy.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

INTEGRATION = (
    Path(__file__).resolve().parents[1] / "custom_components" / "truma_aventa"
)
sys.path.insert(0, str(INTEGRATION))

import truma_ble


def _imported_names(path: Path) -> set[str]:
    """Names a module imports from the truma_ble package itself."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "truma_ble":
            names.update(alias.name for alias in node.names)
    return names


def _ha_modules() -> list[Path]:
    return sorted(p for p in INTEGRATION.glob("*.py") if p.name != "__init__.py")


def test_package_exports_everything_it_promises() -> None:
    """Every name in __all__ must actually exist."""
    missing = [name for name in truma_ble.__all__ if not hasattr(truma_ble, name)]
    assert not missing, f"__all__ lists names that do not exist: {missing}"


@pytest.mark.parametrize("module", _ha_modules(), ids=lambda p: p.name)
def test_ha_modules_import_only_exported_names(module: Path) -> None:
    """Whatever the integration imports from truma_ble must be exported.

    This is the check that would have caught TRUMA_MANUFACTURER_ID being used
    in the config flow while the package never exported it.
    """
    wanted = _imported_names(module)
    missing = sorted(name for name in wanted if not hasattr(truma_ble, name))
    assert not missing, (
        f"{module.name} imports {missing} from truma_ble, which does not export them"
    )
