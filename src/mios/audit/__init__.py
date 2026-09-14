"""Append-only audit trail (MASTER_SYSTEM_DESIGN §15.6).

Two record streams:

* ``audit_log`` — every state change: who/what/when (human, agent, system).
* ``agent_runs`` — every agent/pipeline execution with prompt/model
  versions, token usage and cost.

Records are immutable (:class:`mios.common.schema.MiosRecord`) and sinks are
append-only. Two sinks exist behind the same protocol: JSONL files under
``var/`` for local work, and PostgreSQL for anywhere the filesystem does not
survive the run — which includes every GitHub Actions runner.
"""

from mios.audit.logger import (
    AuditLogger,
    AuditSink,
    JsonlAuditSink,
    PostgresAuditSink,
    TeeAuditSink,
)
from mios.audit.records import ActorKind, AgentRunRecord, AuditRecord

__all__ = [
    "ActorKind",
    "AgentRunRecord",
    "AuditLogger",
    "AuditRecord",
    "AuditSink",
    "JsonlAuditSink",
    "PostgresAuditSink",
    "TeeAuditSink",
]
