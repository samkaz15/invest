"""DimensionReport — the common output contract of every theme engine
(INTELLIGENCE_ENGINE_SPECIFICATION §1.3). The Scoring Engine consumes
only this shape; analyzers are swappable behind it."""

from datetime import datetime

from pydantic import Field, field_validator

from bios.common.errors import BiosError
from bios.common.labels import ClaimLabel, Dimension
from bios.common.schema import BiosModel, BiosRecord
from bios.common.timeutil import ensure_utc


class Signal(BiosModel):
    """One scored observation — the unit of explainability (IES §11.2 L1)."""

    signal_id: str  # e.g. "derivatives.funding_extreme"
    value: float | None
    points: int = Field(ge=-100, le=100)
    label: ClaimLabel
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list)  # raw items / events


class DimensionReport(BiosRecord):
    dimension: Dimension
    asset_id: str
    as_of: datetime
    score: int = Field(ge=-100, le=100)
    conviction: float = Field(ge=0, le=1)
    signals: list[Signal] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list, max_length=5)
    watch_items: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)  # silent gaps forbidden
    invalidation: str = ""
    analyzer_version: str

    @field_validator("as_of")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        try:
            return ensure_utc(v)
        except BiosError as exc:
            raise ValueError(str(exc)) from exc


def compose_report(
    dimension: Dimension,
    asset_id: str,
    as_of: datetime,
    signals: list[Signal],
    gaps: list[str],
    analyzer_version: str,
    key_findings: list[str] | None = None,
    watch_items: list[str] | None = None,
    invalidation: str = "",
) -> DimensionReport:
    """Assemble a report with the standard score/conviction arithmetic:
    score = clipped sum of signal points; conviction scales with data
    completeness (a mostly-gap day must say so numerically)."""
    score = max(-100, min(100, sum(s.points for s in signals)))
    available, missing = len(signals), len(gaps)
    conviction = 0.1 if available == 0 else round(0.9 * available / (available + missing), 2)
    return DimensionReport(
        dimension=dimension,
        asset_id=asset_id,
        as_of=as_of,
        score=score,
        conviction=conviction,
        signals=signals,
        key_findings=(key_findings or [])[:5],
        watch_items=watch_items or [],
        data_gaps=gaps,
        invalidation=invalidation,
        analyzer_version=analyzer_version,
    )
