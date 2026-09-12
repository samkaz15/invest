"""Analysis — macro dimension scores and the two asset views.

Scores are weighted sums of signals, every input stored with its weight and
its contribution. What makes this package different from the scoring engine
it replaces is that each score also records what it structurally cannot
see: a yield-and-dollar model of gold is incomplete, and a reader not told
so will mistake its silence for absence.
"""

from mios.analysis.macro import VERSION, MacroScore, asset_view, score_dimension
from mios.analysis.models import DimensionReport, Signal, compose_report
from mios.analysis.repo import MacroScoreRepo

__all__ = [
    "VERSION",
    "DimensionReport",
    "MacroScore",
    "MacroScoreRepo",
    "Signal",
    "asset_view",
    "compose_report",
    "score_dimension",
]
