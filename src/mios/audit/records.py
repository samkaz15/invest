"""Audit record schemas (MASTER_SYSTEM_DESIGN §15.6)."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator

from mios.common.errors import MiosError
from mios.common.labels import RunStatus
from mios.common.schema import MiosRecord
from mios.common.timeutil import ensure_utc


def _validate_utc(value: datetime) -> datetime:
    """ensure_utc for pydantic validators: raise ValueError so failures
    surface as ValidationError like every other schema violation."""
    try:
        return ensure_utc(value)
    except MiosError as exc:
        raise ValueError(str(exc)) from exc


class ActorKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


class AuditRecord(MiosRecord):
    """One state change: who did what to which object."""

    ts: datetime
    actor_kind: ActorKind
    actor: str  # e.g. "owner", "knowledge_graph", "migration"
    action: str  # e.g. "event.approve", "entity.merge"
    target: str  # id of the object acted upon
    detail: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ts")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _validate_utc(v)


class AgentRunRecord(MiosRecord):
    """One agent/pipeline execution — the cost & provenance unit."""

    run_id: str
    agent: str
    started_at: datetime
    ended_at: datetime
    prompt_version: str  # e.g. "similarity/v007"; "-" for rule-based runs
    model: str  # resolved model id at run time; "-" if no LLM
    status: RunStatus
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    schema_validation: bool = True
    error: str | None = None

    @field_validator("started_at", "ended_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _validate_utc(v)
