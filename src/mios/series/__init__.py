"""Series — the macro time series pipeline.

Covers what the brief calls Agent 2 (macro data) and Agent 3 (rates and
market data) in one package, because the two differ in *which series they
own*, not in how bytes become numbers: both read a provider payload, both
land in the same vintage-keyed table, both are read through the same as-of
query. Splitting them would duplicate the parsing and the repository, which
is exactly the "several agents fetching the same data" shape the brief
warns against. The distinction between them lives in `config/series.yaml`,
where it belongs.
"""

from mios.series.normalize import Normalizer, NormalizeReport
from mios.series.parsers import PARSERS, ParsedPoint, ParseError, get_parser
from mios.series.planner import PlannedWrite, plan_writes
from mios.series.repo import Observation, ObservationRepo, SeriesRepo, WriteResult

__all__ = [
    "PARSERS",
    "NormalizeReport",
    "Normalizer",
    "Observation",
    "ObservationRepo",
    "ParseError",
    "ParsedPoint",
    "PlannedWrite",
    "SeriesRepo",
    "WriteResult",
    "get_parser",
    "plan_writes",
]
