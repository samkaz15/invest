"""Macro dimension scores, and the two asset views built on them.

Each score is a weighted sum of signals, where a signal is one series'
reading turned into points by a configured rule. Nothing is fitted; the
weights are stated and the arithmetic is stored, so a score months old can
still be explained from its own row.

The part worth reading closely is :func:`asset_view`. A chain like

    inflation → Fed expectations → real yield → dollar → gold

is a real transmission mechanism and also an incomplete one. Gold moves on
central-bank buying and on geopolitical risk, neither of which appears in
any yield series; USDJPY moves on MOF intervention, which appears in no
rate differential. Those are recorded as ``blind_spots`` on every asset
view — not as a disclaimer, but because a reader who is not told what the
model cannot see will read its silence as evidence of absence.
"""

from dataclasses import dataclass, field
from datetime import datetime

from mios.analysis.models import Signal
from mios.common.ids import IdKind, make_dated_id
from mios.common.labels import ClaimLabel, Dimension, Stance
from mios.common.logutil import get_logger
from mios.config.analysis import AssetViewSpec, DimensionSpec, SignalSpec
from mios.prediction.features import diff_series, load, mom_series, zscore
from mios.series.repo import ObservationRepo

logger = get_logger(__name__)

VERSION = "macro/v1"

#: Points a single signal may contribute. Keeping every signal on the same
#: scale is what lets weights be read as relative importance rather than as
#: an accident of the units the underlying series happens to use.
SIGNAL_CAP = 25.0

#: Scores within this band are read as "no call". Below it, listing which
#: inputs disagree is noise: when the net is near zero, *everything*
#: disagrees with something, and the honest summary is that the inputs are
#: split rather than a list of three contradictions.
NEUTRAL_BAND = 10.0

#: Above the neutral band, an input has to be worth this share of the net
#: score before it is named as pulling the other way.
CONTRADICTION_SHARE = 0.2


def _contradictions(signals: list[Signal], score: float, noun: str) -> list[str]:
    """Which inputs pull against the net reading, when that question has an
    answer at all.

    Disagreement is information and must never be averaged away — but a
    balanced set of inputs is one finding, not a list of them.
    """
    opposing = [s for s in signals if s.points != 0 and (s.points > 0) != (score > 0)]
    if abs(score) <= NEUTRAL_BAND:
        if any(s.points > 0 for s in signals) and any(s.points < 0 for s in signals):
            return [
                f"入力が拮抗しており方向感なし（スコア {score:+.0f}、±{NEUTRAL_BAND:.0f} の中立帯）"
            ]
        return []
    material = abs(score) * CONTRADICTION_SHARE
    return [
        f"{s.signal_id} {noun} ({s.points:+d}pt)" for s in opposing if abs(s.points) >= material
    ]


@dataclass
class MacroScore:
    """One dimension's reading, with everything needed to replay it."""

    score_id: str
    dimension: str
    as_of: datetime
    score: float
    stance: str
    confidence: float
    signals: list[Signal] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)
    blind_spots: list[str] = field(default_factory=list)
    method_version: str = VERSION


def _reading(repo: ObservationRepo, spec: SignalSpec, as_of: datetime) -> tuple[float | None, str]:
    """One signal's standardised reading and the sentence explaining it."""
    series = load(repo, spec.series_id, as_of)
    if len(series) < spec.min_history:
        return None, f"{spec.series_id}: history n={len(series)} < {spec.min_history}"

    if spec.measure == "level_z":
        values = list(series.values)
        label = "sits"
    elif spec.measure == "change_z":
        values = diff_series(series)
        label = "has moved"
    else:  # trend_z
        values = mom_series(series)
        label = "is running"
    if not values:
        return None, f"{spec.series_id}: no usable readings"

    reading = zscore(values, min_n=spec.min_history)
    if reading is None:
        return None, f"{spec.series_id}: no usable spread in history"
    return reading, f"{spec.label} {label} {reading:+.2f}σ against its own recent history"


def _stance_for(dimension: str, score: float, spec_stance: tuple[str, str, str]) -> str:
    """Words for the number, chosen per dimension.

    A hawkish Fed and a bullish gold view are both "positive scores", and
    calling them the same thing would make every report read like it was
    written by something that did not understand either.
    """
    positive, neutral, negative = spec_stance
    if score > 15:
        return positive
    if score < -15:
        return negative
    return neutral


def score_dimension(repo: ObservationRepo, spec: DimensionSpec, as_of: datetime) -> MacroScore:
    """Score one macro dimension from its configured signals."""
    signals: list[Signal] = []
    gaps: list[str] = []

    for signal_spec in spec.signals:
        reading, note = _reading(repo, signal_spec, as_of)
        if reading is None:
            gaps.append(note)
            continue
        # Bounded before weighting: an outlier reading should move the score,
        # not define it.
        bounded = max(-3.0, min(3.0, reading))
        points = max(-SIGNAL_CAP, min(SIGNAL_CAP, bounded * signal_spec.weight))
        signals.append(
            Signal(
                signal_id=f"{spec.dimension}.{signal_spec.series_id.removeprefix('ser_')}",
                value=round(reading, 4),
                points=round(points),
                label=ClaimLabel.INFERENCE,
                rationale=f"{note} → {points:+.1f}pt",
                evidence_refs=[signal_spec.series_id],
            )
        )

    total = sum(s.points for s in signals)
    score = max(-100.0, min(100.0, float(total)))
    contradictions = _contradictions(signals, score, "points the other way")
    available, missing = len(signals), len(gaps)
    confidence = (
        0.1 if available == 0 else round(min(0.9, 0.9 * available / (available + missing)), 2)
    )

    return MacroScore(
        score_id=make_dated_id(IdKind.SCORE_CARD, as_of.date().isoformat(), spec.dimension),
        dimension=spec.dimension,
        as_of=as_of,
        score=score,
        stance=_stance_for(spec.dimension, score, spec.stance_words),
        confidence=confidence,
        signals=signals,
        contradictions=contradictions,
        data_gaps=gaps,
        blind_spots=list(spec.blind_spots),
    )


def asset_view(
    spec: AssetViewSpec,
    dimensions: dict[str, MacroScore],
    as_of: datetime,
) -> MacroScore:
    """Combine dimension scores into one asset's macro bias.

    Deliberately built from the dimension scores rather than from raw series
    a second time: the transmission chain the brief describes runs *through*
    rates and policy expectations, so reading the same yields twice under
    two names would double-count them and make the view look better
    supported than it is.
    """
    signals: list[Signal] = []
    gaps: list[str] = []
    for link in spec.links:
        source = dimensions.get(link.dimension)
        if source is None:
            gaps.append(f"{link.dimension}: dimension not computed")
            continue
        if not source.signals:
            gaps.append(f"{link.dimension}: no usable signals behind it")
            continue
        points = max(-SIGNAL_CAP, min(SIGNAL_CAP, source.score * link.weight))
        signals.append(
            Signal(
                signal_id=f"{spec.asset_id.removeprefix('ent_asset_')}.{link.dimension}",
                value=round(source.score, 2),
                points=round(points),
                label=ClaimLabel.INFERENCE,
                rationale=f"{link.rationale} — {source.dimension} {source.score:+.0f} "
                f"({source.stance}) → {points:+.1f}pt",
                evidence_refs=[source.score_id],
            )
        )

    total = sum(s.points for s in signals)
    score = max(-100.0, min(100.0, float(total)))
    contradictions = _contradictions(signals, score, "pulls the other way")
    # Confidence inherits from what it was built on: a view assembled from
    # three half-blind dimensions is not a confident view.
    inherited = [
        dimensions[link.dimension].confidence for link in spec.links if link.dimension in dimensions
    ]
    coverage = len(signals) / len(spec.links) if spec.links else 0.0
    confidence = (
        0.1
        if not inherited
        else round(max(0.1, min(0.9, (sum(inherited) / len(inherited)) * coverage)), 2)
    )

    return MacroScore(
        score_id=make_dated_id(
            IdKind.SCORE_CARD, as_of.date().isoformat(), spec.asset_id.removeprefix("ent_asset_")
        ),
        dimension=spec.view_id,
        as_of=as_of,
        score=score,
        stance=_stance_for(spec.view_id, score, spec.stance_words),
        confidence=confidence,
        signals=signals,
        contradictions=contradictions,
        data_gaps=gaps,
        blind_spots=list(spec.blind_spots),
    )


def stance_to_label(stance: str) -> Stance:
    """Map a dimension's own wording back onto the shared vocabulary."""
    if stance in ("hawkish", "bullish", "tightening", "hot"):
        return Stance.BULLISH
    if stance in ("dovish", "bearish", "easing", "cooling"):
        return Stance.BEARISH
    return Stance.NEUTRAL


KNOWN_DIMENSIONS = frozenset(d.value for d in Dimension)
