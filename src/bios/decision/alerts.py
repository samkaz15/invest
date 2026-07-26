"""Alert Engine v1 (MSD §15.4 silent-gap prohibition, IES scoring hooks).

Rule-based, no LLM: alerts fire from thresholds already computed
elsewhere (signal points, breaker state, invalidation checks). This is
the "push" counterpart to the Morning Briefing's "pull".
"""

from typing import Any

from bios.common.schema import BiosModel
from bios.storage.db import Database

SIGNAL_ALERT_THRESHOLD = 15  # |points| at/above this fires an alert (IES dimension scoring)


class Alert(BiosModel):
    severity: str  # info | warning | critical
    category: str  # signal | breaker | invalidation | data_gap
    message: str
    ref: str | None = None


class AlertEngine:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _emit(self, asset_id: str, alert: Alert) -> None:
        self._db.execute(
            """
            INSERT INTO alerts (asset_id, severity, category, message, ref)
            VALUES (%(a)s, %(s)s, %(c)s, %(m)s, %(r)s)
            """,
            {
                "a": asset_id,
                "s": alert.severity,
                "c": alert.category,
                "m": alert.message,
                "r": alert.ref,
            },
        )

    def scan(self, asset_id: str) -> list[Alert]:
        alerts: list[Alert] = []

        card = self._db.query_one(
            "SELECT * FROM score_cards WHERE asset_id=%(a)s ORDER BY as_of DESC LIMIT 1",
            {"a": asset_id},
        )
        if card:
            for entry in card["dimensions"]:
                for signal in entry.get("top_signals", []):
                    points = int(signal.get("points", 0))
                    if abs(points) >= SIGNAL_ALERT_THRESHOLD:
                        alerts.append(
                            Alert(
                                severity="warning" if abs(points) < 25 else "critical",
                                category="signal",
                                message=f"[{entry['dimension']}] {signal.get('rationale')}",
                                ref=str(signal.get("signal_id")),
                            )
                        )
            if card["conflict_index"] >= 0.8:
                alerts.append(
                    Alert(
                        severity="warning",
                        category="signal",
                        message=f"次元間の対立が極端（conflict_index={card['conflict_index']:.2f}）",
                        ref=card["score_card_id"],
                    )
                )

        decision = self._db.query_one(
            "SELECT * FROM decisions WHERE asset_id=%(a)s ORDER BY as_of DESC LIMIT 1",
            {"a": asset_id},
        )
        if decision and decision["action"] == "BUY":
            # Invalidation "firing" in v1 = today's composite has crossed
            # back over the take-profit threshold while a position is open;
            # concrete numeric check happens in decision.engine at decide()
            # time. Here we alert on the presence of an active BUY stance
            # so the owner knows which condition is live.
            alerts.append(
                Alert(
                    severity="info",
                    category="invalidation",
                    message=f"アクティブな無効化条件: {decision['invalidation'].get('condition')}",
                    ref=decision["decision_id"],
                )
            )

        for source in self._db.query(
            "SELECT source_id FROM sources WHERE enabled=false AND kind <> 'seed'"
        ):
            alerts.append(
                Alert(
                    severity="warning",
                    category="data_gap",
                    message=f"ソース無効化中: {source['source_id']}（秘密未設定または障害）",
                    ref=source["source_id"],
                )
            )

        for alert in alerts:
            self._emit(asset_id, alert)
        return alerts

    def recent(self, asset_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self._db.query(
            "SELECT * FROM alerts WHERE asset_id=%(a)s ORDER BY ts DESC LIMIT %(n)s",
            {"a": asset_id, "n": limit},
        )
