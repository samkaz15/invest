"""Storage-layer integration tests against a real PostgreSQL (mios_test).

Skipped automatically when the test database is unreachable, so the unit
suite stays runnable anywhere. Each session rebuilds the schema from the
migrations — the migrations themselves are under test.

The event-store, timeline and entity tests that used to live here went with
the knowledge layer (ADR-015). What is left is what still has a caller:
migrations apply idempotently, and the audit trail reaches the database and
cannot be rewritten once it is there.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mios.config.loader import load_config
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


def test_migrations_are_idempotent(db: Database) -> None:
    assert MigrationRunner(db, REPO / "db" / "migrations").apply_all() == []


def test_audit_records_reach_the_database(db: Database) -> None:
    """A GitHub Actions runner is destroyed after the run.

    An audit trail written only to that runner's filesystem is not an audit
    trail, so the database sink is what makes the record survive
    (docs/ARCHITECTURE.md §6 A-1).
    """
    from mios.audit import ActorKind, AgentRunRecord, AuditLogger, PostgresAuditSink
    from mios.common.labels import RunStatus

    logger = AuditLogger(PostgresAuditSink(db.execute))
    logger.log_action(
        ActorKind.SYSTEM,
        actor="collector",
        action="collect",
        target="src_fred_cpiaucsl",
        detail={"stored": 3},
    )
    logger.log_agent_run(
        AgentRunRecord(
            run_id="run_0123456789abcdef0",
            agent="collector.src_fred_cpiaucsl",
            started_at=datetime(2026, 9, 11, 13, tzinfo=UTC),
            ended_at=datetime(2026, 9, 11, 13, 0, 2, tzinfo=UTC),
            prompt_version="-",
            model="-",
            status=RunStatus.SUCCESS,
            input_refs=["src_fred_cpiaucsl"],
            output_refs=["raw_0123456789abcdef0"],
        )
    )

    [action] = db.query("SELECT * FROM audit_log WHERE target = 'src_fred_cpiaucsl'")
    assert action["detail"] == {"stored": 3}
    [run] = db.query("SELECT * FROM agent_runs WHERE run_id = 'run_0123456789abcdef0'")
    assert run["status"] == "success"


def test_the_audit_trail_cannot_be_rewritten(db: Database) -> None:
    """Same protection as every other append-only table: an audit record
    that could be edited is not evidence."""
    from mios.audit import ActorKind, AuditLogger, PostgresAuditSink

    AuditLogger(PostgresAuditSink(db.execute)).log_action(
        ActorKind.SYSTEM, actor="test", action="probe", target="nothing"
    )
    with pytest.raises(StorageError, match="append-only"):
        db.execute("UPDATE audit_log SET action = 'tampered'")
