"""Append-only audit trail (MASTER_SYSTEM_DESIGN §15.6).

Two record streams:

* ``audit_log`` — every state change: who/what/when (human, agent, system).
* ``agent_runs`` — every agent/pipeline execution with prompt/model
  versions, token usage and cost.

Records are immutable (:class:`bios.common.schema.BiosRecord`) and sinks are
append-only. Sprint 1 ships the JSONL file sink; the PostgreSQL sink arrives
with the storage layer (Sprint 3) behind the same ``AuditSink`` protocol.
"""

from bios.audit.logger import AuditLogger, AuditSink, JsonlAuditSink
from bios.audit.records import ActorKind, AgentRunRecord, AuditRecord

__all__ = [
    "ActorKind",
    "AgentRunRecord",
    "AuditLogger",
    "AuditRecord",
    "AuditSink",
    "JsonlAuditSink",
]
