"""Audit sinks and the logging facade."""

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from bios.audit.records import ActorKind, AgentRunRecord, AuditRecord
from bios.common.errors import AuditWriteError
from bios.common.schema import BiosRecord
from bios.common.timeutil import utc_now


class AuditSink(Protocol):
    """Where audit records go. Implementations must be append-only."""

    def append(self, stream: str, record: BiosRecord) -> None: ...


class JsonlAuditSink:
    """One JSONL file per stream under ``root`` (var/audit by default).

    Simple, greppable, durable enough for Phase 1. Replaced/mirrored by the
    PostgreSQL sink in Sprint 3 without touching callers.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True)

    def append(self, stream: str, record: BiosRecord) -> None:
        path = self._root / f"{stream}.jsonl"
        line = record.model_dump_json() + "\n"
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
        except OSError as exc:
            raise AuditWriteError(f"cannot append to audit stream {stream!r}: {exc}") from exc


class AuditLogger:
    """Facade used by all layers to emit audit records."""

    AUDIT_STREAM = "audit_log"
    RUNS_STREAM = "agent_runs"

    def __init__(self, sink: AuditSink) -> None:
        self._sink = sink

    def log_action(
        self,
        actor_kind: ActorKind,
        actor: str,
        action: str,
        target: str,
        ts: datetime | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditRecord:
        record = AuditRecord(
            ts=ts or utc_now(),
            actor_kind=actor_kind,
            actor=actor,
            action=action,
            target=target,
            detail=detail or {},
        )
        self._sink.append(self.AUDIT_STREAM, record)
        return record

    def log_agent_run(self, record: AgentRunRecord) -> AgentRunRecord:
        self._sink.append(self.RUNS_STREAM, record)
        return record
