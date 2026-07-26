"""`bios why <decision_id>`: full evidence chain, decision -> score card ->
signals -> events/raw items -> source tier. This is the audit trail MSD
§18 requires ("any Decision must be traceable to its source Evidence").
"""

from typing import Any

from bios.storage.db import Database


class WhyExplainer:
    def __init__(self, db: Database) -> None:
        self._db = db

    def explain(self, decision_id: str) -> str:
        decision = self._db.query_one(
            "SELECT * FROM decisions WHERE decision_id=%(i)s", {"i": decision_id}
        )
        if decision is None:
            return f"decision {decision_id} not found"

        card = self._db.query_one(
            "SELECT * FROM score_cards WHERE score_card_id=%(i)s",
            {"i": decision["score_card_id"]},
        )
        scenario_set = self._db.query_one(
            "SELECT * FROM scenario_sets WHERE scenario_set_id=%(i)s",
            {"i": decision["scenario_set_id"]},
        )

        lines = [
            f"decision {decision_id}: {decision['action']} "
            f"(conviction={decision['conviction']:.2f})",
            f"  rationale: {decision['rationale']}",
            f"  counter_argument: {decision['counter_argument']}",
            f"  invalidation: {decision['invalidation']}",
            "",
            f"score_card {decision['score_card_id']}: composite={card['composite']:+d} "
            f"({card['verdict_hint']}) weights={card['weights_version']}"
            if card
            else "  score_card: MISSING",
        ]
        if card:
            for entry in card["dimensions"]:
                lines.append(
                    f"  ├ {entry['dimension']} score={entry['score']:+d} "
                    f"weight={entry['weight']} contribution={entry['contribution']:+.1f}"
                )
                for signal in entry["top_signals"]:
                    lines.append(
                        f"  │   signal {signal['signal_id']}: points={signal['points']:+d} "
                        f"label={signal['label']} — {signal['rationale']}"
                    )
                    for ref in signal.get("evidence_refs", []):
                        lines.append(f"  │     evidence_ref -> {ref}")

        if scenario_set:
            lines.append("")
            lines.append(
                f"scenario_set {decision['scenario_set_id']} ({scenario_set['method_version']}):"
            )
            for scenario in scenario_set["scenarios"]:
                lines.append(f"  ├ {scenario['name']}: {scenario['probability']:.0%}")
                for ref in scenario["rationale_refs"]:
                    lines.append(f"  │   rationale_ref -> {ref}")

        lines.append("")
        lines.append("rationale_refs (signal_ids cited in the decision):")
        for ref in decision["rationale_refs"]:
            lines.append(f"  - {ref}")

        return "\n".join(lines)

    def event_provenance(self, event_id: str) -> str:
        """Trace one event back through evidence to its raw item / source tier
        (the other half of the audit trail: Fact -> Evidence -> Source)."""
        event = self._db.query_one("SELECT * FROM events WHERE event_id=%(e)s", {"e": event_id})
        if event is None:
            return f"event {event_id} not found"
        evidence_rows: list[dict[str, Any]] = self._db.query(
            """
            SELECT e.* FROM evidences e JOIN event_evidences ee ON ee.evidence_id = e.evidence_id
            WHERE ee.event_id = %(e)s
            """,
            {"e": event_id},
        )
        lines = [f"event {event_id}: {event['title']} ({event['type']}, {event['confidence']})"]
        for ev in evidence_rows:
            source = self._db.query_one(
                "SELECT * FROM sources WHERE source_id=%(s)s", {"s": ev["source_id"]}
            )
            tier = source["tier"] if source else ev["tier"]
            lines.append(f"  ├ evidence {ev['evidence_id']} (tier {tier}): {ev['url']}")
            if ev["raw_item_id"]:
                lines.append(f"  │   raw_item_id -> {ev['raw_item_id']}")
        return "\n".join(lines)
