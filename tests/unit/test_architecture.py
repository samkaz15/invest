"""Layer-boundary guard: import direction is a design rule, not a habit.

Imports flow one way. Each mios subpackage may import only from the
packages listed here. Adding an edge is an architectural decision — change
this table consciously, in review.

This test is the reason the Bitcoin-specific layers could be removed
without the rest unravelling, so it is the first thing that gets updated
when a layer is added (docs/REPOSITORY_AUDIT.md §6.1).
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "mios"

ALLOWED: dict[str, set[str]] = {
    "common": set(),
    "config": {"common"},
    "audit": {"common"},
    "storage": {"common", "config"},
    "scheduler": {"common", "config", "audit"},
    # ingestion -> scheduler: the collector uses the RateLimiter primitive;
    # scheduler never imports ingestion (tasks are injected), so still one-way.
    "ingestion": {"common", "config", "audit", "storage", "scheduler"},
    "extraction": {"common", "config", "audit", "storage", "ingestion", "knowledge"},
    "series": {"common", "config", "audit", "storage", "ingestion"},
    "prediction": {"common", "config", "audit", "storage", "series"},
    "knowledge": {"common", "config", "audit", "storage"},
    "analysis": {"common", "config", "audit", "storage", "knowledge"},
    "scoring": {"common", "config", "audit", "storage", "knowledge", "analysis"},
}


def _mios_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("mios."):
            found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("mios."):
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
            for imported in _mios_imports(py):
                if imported not in allowed:
                    violations.append(f"{py.relative_to(SRC)}: imports mios.{imported}")
    assert not violations, "layer-boundary violations:\n" + "\n".join(violations)


def test_every_package_is_registered() -> None:
    unknown = {p.name for p in _packages()} - set(ALLOWED)
    assert not unknown, f"register new packages in ALLOWED consciously: {unknown}"


def test_no_empty_placeholder_packages() -> None:
    """A package that holds only a docstring is a promise, not code.

    BIOS carried two of them (``agents``, ``similarity``) for six sprints
    (docs/REPOSITORY_AUDIT.md §8 U-1, U-2). A package now earns its
    directory by containing at least one module.
    """
    empty = [
        p.name for p in _packages() if not [f for f in p.rglob("*.py") if f.name != "__init__.py"]
    ]
    assert not empty, f"packages with no modules — create them when they have code: {empty}"
