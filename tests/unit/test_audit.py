"""Audit trail tests: append-only, immutable, well-formed."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from bios.audit import ActorKind, AgentRunRecord, AuditLogger, JsonlAuditSink
from bios.common import IdKind, RunStatus, new_id


@pytest.fixture
def logger(tmp_path: Path) -> AuditLogger:
    return AuditLogger(JsonlAuditSink(tmp_path))


def _run_record(**overrides: object) -> AgentRunRecord:
    base: dict[str, object] = {
        "run_id": new_id(IdKind.AGENT_RUN),
        "agent": "news",
        "started_at": datetime(2026, 7, 14, 5, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 7, 14, 5, 1, tzinfo=UTC),
        "prompt_version": "news/v001",
        "model": "test-model",
        "status": RunStatus.SUCCESS,
        "tokens_in": 100,
        "tokens_out": 10,
    }
    base.update(overrides)
    return AgentRunRecord.model_validate(base)


def test_actions_append_as_jsonl(logger: AuditLogger, tmp_path: Path) -> None:
    logger.log_action(ActorKind.HUMAN, "owner", "event.approve", "evt_2024-01-10_etf-approval")
    logger.log_action(ActorKind.AGENT, "knowledge_graph", "entity.merge", "ent_x", into="ent_y")
    lines = (tmp_path / "audit_log.jsonl").read_text().splitlines()
    assert len(lines) == 2  # appended, not overwritten
    first, second = (json.loads(line) for line in lines)
    assert first["action"] == "event.approve"
    assert second["detail"] == {"into": "ent_y"}


def test_agent_runs_go_to_their_own_stream(logger: AuditLogger, tmp_path: Path) -> None:
    logger.log_agent_run(_run_record())
    assert (tmp_path / "agent_runs.jsonl").exists()
    assert not (tmp_path / "audit_log.jsonl").exists()


def test_naive_timestamps_rejected() -> None:
    with pytest.raises(ValidationError):
        _run_record(started_at=datetime(2026, 7, 14, 5, 0))


def test_negative_token_counts_rejected() -> None:
    with pytest.raises(ValidationError):
        _run_record(tokens_in=-1)


def test_records_are_immutable(logger: AuditLogger) -> None:
    record = logger.log_action(ActorKind.SYSTEM, "migration", "schema.apply", "0001")
    with pytest.raises(ValidationError):
        record.action = "tampered"  # type: ignore[misc]
