"""MIOS — Macro Intelligence Operating System.

A research infrastructure that snapshots the world's macroeconomic state
every day and keeps enough provenance to check, months later, whether its
CPI/NFP forecasts were any good. It is not a price-prediction AI.

Layers map one-to-one to subpackages (see docs/ARCHITECTURE.md); imports
flow only from downstream layers to upstream ones, never the reverse, and
tests/unit/test_architecture.py enforces it.
"""

__version__ = "0.2.0"
