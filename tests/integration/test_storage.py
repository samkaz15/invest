"""Storage-layer integration tests against a real PostgreSQL (mios_test).

Skipped automatically when the test database is unreachable, so the unit
suite stays runnable anywhere. Each test session rebuilds the schema from
migrations — the migrations themselves are under test.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mios.common import SourceTier
from mios.common.labels import ChainStatus, EventConfidence
from mios.common.timeutil import TimePrecision
from mios.config.loader import load_config
from mios.knowledge.graph import ChainRepo, EntityRepo
from mios.knowledge.models import (
    ChainRecord,
    EntityRecord,
    EventRecord,
    EvidenceRecord,
    RelationRecord,
)
from mios.knowledge.snapshots import SnapshotRepo
from mios.knowledge.store import CurationQueue, EventStore, IntegrityError
from mios.knowledge.timeline import TimelineEngine
from mios.storage.db import Database, StorageError
from mios.storage.migrate import MigrationRunner
from mios.storage.sync import sync_sources

REPO = Path(__file__).resolve().parents[2]
TEST_DSN = os.environ.get("MIOS_TEST_DATABASE_URL", "postgresql://localhost/mios_test")


@pytest.fixture(scope="module")
def db() -> Database:
    database = Database(TEST_DSN)
    if not database.ping():
        pytest.skip(f"test database unreachable: {TEST_DSN}")
    database.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    MigrationRunner(database, REPO / "db" / "migrations").apply_all()
    sync_sources(database, load_config(REPO / "config").sources)
    return database


@pytest.fixture(scope="module")
def store(db: Database) -> EventStore:
    return EventStore(db, load_config(REPO / "config").events)


def _evidence(n: int) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=f"evd_{n:017d}",
        source_id="src_fred_cpiaucsl",
        tier=SourceTier.OFFICIAL,
        url="https://www.bls.gov/news.release/cpi.nr0.htm",
        quote="The CPI rose 0.3 percent in August",
        retrieved_at=datetime(2024, 1, 11, tzinfo=UTC),
    )


def _event(event_id: str, occurred: datetime, chain_id: str | None = None) -> EventRecord:
    return EventRecord(
        event_id=event_id,
        type="release.us_inflation.cpi",
        title="t",
        summary_fact="s",
        occurred_at=occurred,
        known_at=occurred,
        time_precision=TimePrecision.DAY,
        confidence=EventConfidence.VERIFIED,
        chain_id=chain_id,
        assets=[{"asset_id": "ent_asset_xauusd", "relevance": 1.0}],
    )


def test_migrations_are_idempotent(db: Database) -> None:
    assert MigrationRunner(db, REPO / "db" / "migrations").apply_all() == []


def test_event_requires_evidence(store: EventStore) -> None:
    with pytest.raises(IntegrityError, match="at least one evidence"):
        store.insert_event(
            _event("evt_2026-01-10_no-evidence", datetime(2024, 1, 10, tzinfo=UTC)), []
        )


def test_event_type_must_be_in_taxonomy(store: EventStore) -> None:
    bad = _event("evt_2024-01-10_bad-type", datetime(2024, 1, 10, tzinfo=UTC))
    bad = bad.model_copy(update={"type": "made.up.type"})
    with pytest.raises(IntegrityError, match="unknown event type"):
        store.insert_event(bad, [_evidence(90)])


def test_events_are_append_only_in_the_database(db: Database, store: EventStore) -> None:
    store.insert_event(
        _event("evt_2024-01-10_etf-approval", datetime(2024, 1, 10, 21, tzinfo=UTC)),
        [_evidence(1)],
        participations=[],
    )
    with pytest.raises(StorageError, match="append-only"):
        db.execute(
            "UPDATE events SET title='tampered' WHERE event_id='evt_2024-01-10_etf-approval'"
        )
    with pytest.raises(StorageError, match="append-only"):
        db.execute("DELETE FROM events WHERE event_id='evt_2024-01-10_etf-approval'")


def test_causal_edge_without_evidence_rejected_by_db(db: Database, store: EventStore) -> None:
    store.insert_event(
        _event("evt_2024-01-11_follow-up", datetime(2024, 1, 11, tzinfo=UTC)),
        [_evidence(2)],
    )
    with pytest.raises(StorageError):
        db.execute(
            "INSERT INTO event_relations (from_event, to_event, rel_type, created_by) VALUES "
            "('evt_2024-01-11_follow-up','evt_2024-01-10_etf-approval','TRIGGERED_BY','test')"
        )
    # PRECEDES (no causal claim) is fine without evidence
    db.execute(
        "INSERT INTO event_relations (from_event, to_event, rel_type, created_by) VALUES "
        "('evt_2024-01-10_etf-approval','evt_2024-01-11_follow-up','PRECEDES','test')"
    )


def test_relation_model_enforces_causal_discipline() -> None:
    with pytest.raises(ValueError, match="requires evidence"):
        RelationRecord(
            from_event="evt_2024-01-11_a",
            to_event="evt_2024-01-10_b",
            rel_type="TRIGGERED_BY",
            created_by="test",
        )


def test_timeline_as_of_hides_later_knowledge(db: Database, store: EventStore) -> None:
    chain = ChainRecord(
        chain_id="chain_test", title="c", chain_type="test", status=ChainStatus.ACTIVE
    )
    ChainRepo(db).upsert(chain)
    early = _event("evt_2024-02-01_early", datetime(2024, 2, 1, tzinfo=UTC), "chain_test")
    # occurred in Feb but only became known in March (e.g. wallet attribution)
    late_known = _event("evt_2024-02-02_late-known", datetime(2024, 2, 2, tzinfo=UTC), "chain_test")
    late_known = late_known.model_copy(update={"known_at": datetime(2024, 3, 1, tzinfo=UTC)})
    store.insert_event(early, [_evidence(3)])
    store.insert_event(late_known, [_evidence(4)])

    timeline = TimelineEngine(db)
    window = (datetime(2024, 1, 20, tzinfo=UTC), datetime(2024, 4, 1, tzinfo=UTC))
    all_events = timeline.events_between(*window, chain_id="chain_test")
    assert [e["event_id"] for e in all_events] == [
        "evt_2024-02-01_early",
        "evt_2024-02-02_late-known",
    ]
    # As of Feb 15, the late-known event must be invisible (look-ahead exclusion)
    as_of = timeline.events_between(
        *window, chain_id="chain_test", as_of=datetime(2024, 2, 15, tzinfo=UTC)
    )
    assert [e["event_id"] for e in as_of] == ["evt_2024-02-01_early"]


def test_entity_upsert_and_alias_lookup(db: Database) -> None:
    EntityRepo(db).upsert(
        EntityRecord(
            entity_id="ent_federal_reserve",
            kind="central_bank",
            name="Federal Reserve",
            aliases=["FRB", "連邦準備制度"],
        )
    )
    found = EntityRepo(db).find_by_name("連邦準備制度")
    assert found and found[0]["entity_id"] == "ent_federal_reserve"


def test_snapshot_upsert_merges_metrics(db: Database) -> None:
    """Pins the CURRENT behaviour of the legacy market_snapshots table.

    This merge-in-place is exactly why the table cannot hold economic data:
    a revised print would overwrite what was knowable at the time
    (docs/REPOSITORY_AUDIT.md §4.1 problem A). Phase 3 replaces it with
    vintage-keyed `observations`; until then this test documents what the
    table does, not what MIOS should do.
    """
    repo = SnapshotRepo(db)
    ts = datetime(2026, 7, 14, 6, tzinfo=UTC)
    repo.upsert("ent_asset_xauusd", ts, 100000.0, None, {"funding_rate": 0.0001})
    repo.upsert("ent_asset_xauusd", ts, 100000.0, None, {"fear_greed": 55.0})
    latest = repo.latest("ent_asset_xauusd")
    assert latest is not None
    assert latest["asset_metrics"] == {"funding_rate": 0.0001, "fear_greed": 55.0}


def test_curation_queue_dedupes_and_resolves(db: Database) -> None:
    queue = CurationQueue(db)
    assert queue.enqueue("src_fred_cpiaucsl", {"title": "x"}, dedupe_key="k1") is True
    assert queue.enqueue("src_fred_cpiaucsl", {"title": "x again"}, dedupe_key="k1") is False
    pending = queue.pending()
    assert len(pending) == 1
    queue.resolve(pending[0]["candidate_id"], "rejected", note="not market relevant")
    assert queue.pending() == []
