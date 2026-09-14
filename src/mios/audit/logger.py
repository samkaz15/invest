"""Audit sinks and the logging facade."""

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from mios.audit.records import ActorKind, AgentRunRecord, AuditRecord
from mios.common.errors import AuditWriteError
from mios.common.schema import MiosRecord
from mios.common.timeutil import utc_now


class AuditSink(Protocol):
    """Where audit records go. Implementations must be append-only."""

    def append(self, stream: str, record: MiosRecord) -> None: ...


class JsonlAuditSink:
    """One JSONL file per stream under ``root`` (var/audit by default).

    Simple, greppable, durable enough for Phase 1. Replaced/mirrored by the
    PostgreSQL sink in Sprint 3 without touching callers.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True)

    def append(self, stream: str, record: MiosRecord) -> None:
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


class PostgresAuditSink:
    """Audit records into the database.

    The JSONL sink writes under ``var/``, which is fine on a workstation and
    useless in CI: a GitHub Actions runner is destroyed after every run, so
    the record of what the nightly job did would vanish with it
    (docs/ARCHITECTURE.md §6 A-1). The tables have existed since migration
    0001; this connects them.

    Append-only is enforced by the same database triggers as everything
    else, so an audit trail cannot be quietly rewritten either.
    """

    AUDIT_STREAM = "audit_log"
    RUNS_STREAM = "agent_runs"

    def __init__(self, execute: "Callable[[str, dict[str, Any]], None]") -> None:
        # Takes a callable rather than a Database so the audit package keeps
        # its one-way dependency: storage may not be imported from here.
        self._execute = execute

    def append(self, stream: str, record: MiosRecord) -> None:
        data = record.model_dump(mode="python")
        try:
            if stream == self.RUNS_STREAM:
                self._append_run(data)
            elif stream == self.AUDIT_STREAM:
                self._append_action(data)
            else:
                raise AuditWriteError(f"unknown audit stream {stream!r}")
        except AuditWriteError:
            raise
        except Exception as exc:  # storage errors must not be swallowed
            raise AuditWriteError(f"cannot append to audit stream {stream!r}: {exc}") from exc

    def _append_action(self, data: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT INTO audit_log (ts, actor_kind, actor, action, target, detail)
            VALUES (%(ts)s, %(actor_kind)s, %(actor)s, %(action)s, %(target)s, %(detail)s)
            """,
            {**data, "detail": json.dumps(data.get("detail", {}), ensure_ascii=False)},
        )

    def _append_run(self, data: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT INTO agent_runs (run_id, agent, started_at, ended_at, prompt_version,
                model, status, input_refs, output_refs, tokens_in, tokens_out, cost_usd,
                schema_validation, error)
            VALUES (%(run_id)s, %(agent)s, %(started_at)s, %(ended_at)s, %(prompt_version)s,
                %(model)s, %(status)s, %(input_refs)s, %(output_refs)s, %(tokens_in)s,
                %(tokens_out)s, %(cost_usd)s, %(schema_validation)s, %(error)s)
            ON CONFLICT (run_id) DO NOTHING
            """,
            {
                **data,
                "status": str(data["status"]),
                "input_refs": json.dumps(data.get("input_refs", []), ensure_ascii=False),
                "output_refs": json.dumps(data.get("output_refs", []), ensure_ascii=False),
            },
        )


class TeeAuditSink:
    """Write to several sinks, failing if any of them fails.

    Used so a run records to both the local JSONL files and the database
    without the caller having to know which one is durable in this
    environment.
    """

    def __init__(self, *sinks: AuditSink) -> None:
        self._sinks = sinks

    def append(self, stream: str, record: MiosRecord) -> None:
        for sink in self._sinks:
            sink.append(stream, record)
