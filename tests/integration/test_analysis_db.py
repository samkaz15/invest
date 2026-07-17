"""Integration tests: dimension-report persistence, market reactions,
and the curation approve flow — against the real test database."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bios.analysis.models import Signal, compose_report
from bios.analysis.reactions import ReactionBatch
from bios.analysis.repo import AnalysisRepo
from bios.common import SourceTier
from bios.common.labels import ClaimLabel, Dimension, EventConfidence
from bios.common.timeutil import TimePrecision
from bios.config.loader import load_config
from bios.knowledge.curation import approve_candidate
from bios.knowledge.models import EventRecord, EvidenceRecord
from bios.knowledge.snapshots import SnapshotRepo
from bios.knowledge.store import CurationQueue, EventStore
from bios.storage.db import Database
from bios.storage.migrate import MigrationRunner
from bios.storage.sync import sync_sources
from tests.integration.test_storage import TEST_DSN

REPO = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def db() -> Database:
    database = Database(TEST_DSN)
    if not database.ping():
        pytest.skip(f"test database unreachable: {TEST_DSN}")
    database.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    MigrationRunner(database, REPO / "db" / "migrations").apply_all()
    sync_sources(database, load_config(REPO / "config").sources)
    return database


def test_dimension_report_roundtrip(db: Database) -> None:
    repo = AnalysisRepo(db)
    signal = Signal(
        signal_id="derivatives.funding_neutral",
        value=0.0001,
        points=0,
        label=ClaimLabel.FACT,
        rationale="neutral",
    )
    report = compose_report(Dimension.DERIVATIVES, "ent_asset_btc", T0, [signal], ["gap"], "v1")
    repo.save_report(report)
    repo.save_report(report)  # idempotent upsert
    rows = repo.latest_reports("ent_asset_btc")
    assert len(rows) == 1
    assert rows[0]["signals"][0]["signal_id"] == "derivatives.funding_neutral"


def test_reaction_batch_stamps_returns(db: Database) -> None:
    snapshots = SnapshotRepo(db)
    # price path: 100 at event, 110 one hour later, 90 one day later
    snapshots.upsert("ent_asset_btc", T0, 100.0, None, {})
    snapshots.upsert("ent_asset_btc", T0 + timedelta(hours=1), 110.0, None, {})
    snapshots.upsert("ent_asset_btc", T0 + timedelta(days=1), 90.0, None, {})
    store = EventStore(db, load_config(REPO / "config").events)
    store.insert_event(
        EventRecord(
            event_id="evt_2026-06-01_reaction-probe",
            type="regulation.etf.approval",
            title="t",
            summary_fact="s",
            occurred_at=T0,
            known_at=T0,
            time_precision=TimePrecision.MINUTE,
            confidence=EventConfidence.VERIFIED,
            assets=[{"asset_id": "ent_asset_btc", "relevance": 1.0}],
        ),
        [
            EvidenceRecord(
                evidence_id="evd_00000000000000021",
                source_id="src_sec_press_rss",
                tier=SourceTier.PRIMARY,
                retrieved_at=T0,
            )
        ],
    )
    stats = ReactionBatch(db, AnalysisRepo(db)).run("ent_asset_btc")
    assert stats["computed"] >= 2
    reactions = {
        r["horizon"]: r for r in AnalysisRepo(db).reactions_for("evt_2026-06-01_reaction-probe")
    }
    assert reactions["+1h"]["return"] == pytest.approx(0.10)
    assert reactions["+1d"]["return"] == pytest.approx(-0.10)
    assert "+90d" not in reactions  # future horizon waits; nothing fabricated


def test_curation_approve_creates_evidenced_event(db: Database) -> None:
    queue = CurationQueue(db)
    store = EventStore(db, load_config(REPO / "config").events)
    payload = {
        "kind": "news",
        "title": "SEC approves new spot ETF",
        "link": "https://example.com/etf",
        "published_raw": "Mon, 01 Jun 2026 05:00:00 GMT",
        "summary": "approval summary",
        "source_id": "src_sec_press_rss",
        "tier": 1,
        "raw_item_id": "raw_00000000000abcdef",
        "retrieved_at": T0.isoformat(),
    }
    assert queue.enqueue("src_sec_press_rss", payload, dedupe_key="approve-flow-1")
    candidate = queue.pending(limit=100)[-1]
    event = approve_candidate(
        store, queue, candidate, event_type="regulation.etf.approval", magnitude=4
    )
    assert event.event_id == "evt_2026-06-01_sec-approves-new-spot-etf"
    assert event.confidence is EventConfidence.VERIFIED  # tier-1 source
    stored = store.get(event.event_id)
    assert stored is not None and stored["magnitude_initial"] == 4
    # queue resolved and linked to the event
    resolved = db.query_one(
        "SELECT status, event_id FROM curation_queue WHERE candidate_id=%(c)s",
        {"c": candidate["candidate_id"]},
    )
    assert resolved == {"status": "approved", "event_id": event.event_id}
    # evidence chain: event -> evidence -> raw item reference
    evidence = db.query(
        "SELECT e.* FROM evidences e JOIN event_evidences ee ON ee.evidence_id=e.evidence_id "
        "WHERE ee.event_id=%(ev)s",
        {"ev": event.event_id},
    )
    assert evidence and evidence[0]["raw_item_id"] == "raw_00000000000abcdef"
