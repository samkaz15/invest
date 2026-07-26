"""Scoring Engine (IES §11): DimensionReports -> 3-layer Score Card.

All arithmetic is deterministic and documented; same inputs always give
the same card (backtestability). Conflict between dimensions is surfaced,
never averaged away (IES §11.4).
"""

import json
from datetime import datetime
from typing import Any

from bios.common.ids import IdKind, make_dated_id
from bios.common.labels import Dimension
from bios.common.schema import BiosModel
from bios.config.models import ScoringConfig
from bios.scoring.regime import Regime
from bios.storage.db import Database

VERSION = "composite/v1"


class DimensionEntry(BiosModel):
    dimension: str
    score: int
    conviction: float
    weight: float
    contribution: float
    top_signals: list[dict[str, Any]]
    data_gaps: list[str]


class ScoreCard(BiosModel):
    score_card_id: str
    asset_id: str
    as_of: datetime
    composite: int
    verdict_hint: str
    conflict_index: float
    data_completeness: float
    weights_version: str
    phase: dict[str, str]
    dimensions: list[DimensionEntry]


def verdict_for(composite: int) -> str:
    if composite > 40:
        return "STRONG_BULLISH"
    if composite > 15:
        return "BULLISH"
    if composite < -40:
        return "STRONG_BEARISH"
    if composite < -15:
        return "BEARISH"
    return (
        "NEUTRAL_BULLISH" if composite > 0 else ("NEUTRAL_BEARISH" if composite < 0 else "NEUTRAL")
    )


def _conflict_index(weighted: list[tuple[float, int]]) -> float:
    """Sign disagreement among non-zero dimensions, weight-aware (0..1).
    1.0 = opinionated dimensions split evenly; 0 = unanimous or silent."""
    positive = sum(w for w, s in weighted if s > 0)
    negative = sum(w for w, s in weighted if s < 0)
    total = positive + negative
    if total == 0:
        return 0.0
    return round(2 * min(positive, negative) / total, 2)


def build_score_card(
    asset_id: str,
    asset_slug: str,
    as_of: datetime,
    reports: list[dict[str, Any]],
    scoring: ScoringConfig,
    regime: Regime,
) -> ScoreCard:
    weights = scoring.weight_sets.get(regime.phase_key(), scoring.weight_sets["default"])
    entries: list[DimensionEntry] = []
    weighted: list[tuple[float, int]] = []
    for report in reports:
        dim = report["dimension"]
        weight = weights.get(dim, 0.0)
        score = int(report["score"])
        if dim == Dimension.ANOMALY.value:  # hard cap (IES §8.3)
            score = max(-scoring.anomaly_points_cap, min(scoring.anomaly_points_cap, score))
        entries.append(
            DimensionEntry(
                dimension=dim,
                score=score,
                conviction=float(report["conviction"]),
                weight=weight,
                contribution=round(weight * score, 1),
                top_signals=sorted(
                    report.get("signals", []), key=lambda s: abs(s.get("points", 0)), reverse=True
                )[:3],
                data_gaps=report.get("data_gaps", []),
            )
        )
        weighted.append((weight, score))

    total_weight = sum(w for w, _ in weighted)
    composite = round(sum(w * s for w, s in weighted) / total_weight) if total_weight else 0
    completeness = round(sum(e.conviction for e in entries) / len(entries), 2) if entries else 0.0
    return ScoreCard(
        score_card_id=make_dated_id(IdKind.SCORE_CARD, as_of.date().isoformat(), asset_slug),
        asset_id=asset_id,
        as_of=as_of,
        composite=composite,
        verdict_hint=verdict_for(composite),
        conflict_index=_conflict_index(weighted),
        data_completeness=completeness,
        weights_version=scoring.weights_version,
        phase={
            "key": regime.phase_key(),
            "trend": regime.trend,
            "vol": regime.vol,
            "liquidity": regime.liquidity,
        },
        dimensions=entries,
    )


class ScoreCardRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, card: ScoreCard) -> bool:
        """Append-only: one card per (asset, day). Returns False if it exists."""
        if self._db.query_one(
            "SELECT 1 AS x FROM score_cards WHERE score_card_id=%(i)s", {"i": card.score_card_id}
        ):
            return False
        data = card.model_dump(mode="json")
        data["phase"] = json.dumps(data["phase"], ensure_ascii=False)
        data["dimensions"] = json.dumps(data["dimensions"], ensure_ascii=False)
        self._db.execute(
            """
            INSERT INTO score_cards (score_card_id, asset_id, as_of, composite, verdict_hint,
                conflict_index, data_completeness, weights_version, phase, dimensions)
            VALUES (%(score_card_id)s, %(asset_id)s, %(as_of)s, %(composite)s, %(verdict_hint)s,
                %(conflict_index)s, %(data_completeness)s, %(weights_version)s, %(phase)s,
                %(dimensions)s)
            """,
            data,
        )
        return True

    def get(self, score_card_id: str) -> dict[str, Any] | None:
        return self._db.query_one(
            "SELECT * FROM score_cards WHERE score_card_id=%(i)s", {"i": score_card_id}
        )

    def save_regime(self, asset_id: str, as_of: datetime, regime: Regime) -> None:
        self._db.execute(
            """
            INSERT INTO regimes (asset_id, date, trend, vol, liquidity, version)
            VALUES (%(a)s, %(d)s, %(t)s, %(v)s, %(l)s, %(ver)s)
            ON CONFLICT (asset_id, date) DO UPDATE SET
                trend=EXCLUDED.trend, vol=EXCLUDED.vol, liquidity=EXCLUDED.liquidity,
                version=EXCLUDED.version, computed_at=now()
            """,
            {
                "a": asset_id,
                "d": as_of.date(),
                "t": regime.trend,
                "v": regime.vol,
                "l": regime.liquidity,
                "ver": regime.version,
            },
        )
