"""Layer-boundary guard: import direction is a design rule, not a habit.

MASTER_SYSTEM_DESIGN §2.1: imports flow one way. Each bios subpackage may
import only from the packages listed here. Adding an edge is an
architectural decision — change this table consciously, in review.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "bios"

ALLOWED: dict[str, set[str]] = {
    "common": set(),
    "config": {"common"},
    "audit": {"common"},
    "storage": {"common", "config"},
    "scheduler": {"common", "config", "audit"},
    "ingestion": {"common", "config", "audit", "storage"},
    "extraction": {"common", "config", "audit", "storage", "ingestion"},
    "knowledge": {"common", "config", "audit", "storage"},
    "history": {"common", "config", "audit", "storage", "knowledge"},
    "analysis": {"common", "config", "audit", "storage", "knowledge", "history"},
    "similarity": {"common", "config", "audit", "storage", "knowledge", "history"},
    "scoring": {"common", "config", "audit", "storage", "knowledge", "analysis", "similarity"},
    "scenario": {"common", "config", "audit", "storage", "knowledge", "similarity", "scoring"},
    "decision": {"common", "config", "audit", "storage", "scenario", "scoring"},
    "reporting": {
        "common",
        "config",
        "audit",
        "storage",
        "knowledge",
        "analysis",
        "similarity",
        "scoring",
        "scenario",
        "decision",
    },
    "agents": {"common", "config", "audit"},
}


def _bios_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("bios."):
            found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("bios."):
                    found.add(alias.name.split(".")[1])
    return found


def _packages() -> list[Path]:
    return sorted(p for p in SRC.iterdir() if p.is_dir() and (p / "__init__.py").exists())


def test_import_direction_is_one_way() -> None:
    violations: list[str] = []
    for pkg_dir in _packages():
        pkg = pkg_dir.name
        allowed = ALLOWED.get(pkg, set()) | {pkg}
        for py in pkg_dir.rglob("*.py"):
            for imported in _bios_imports(py):
                if imported not in allowed:
                    violations.append(f"{py.relative_to(SRC)}: imports bios.{imported}")
    assert not violations, "layer-boundary violations:\n" + "\n".join(violations)


def test_every_package_is_registered() -> None:
    unknown = {p.name for p in _packages()} - set(ALLOWED)
    assert not unknown, f"register new packages in ALLOWED consciously: {unknown}"
