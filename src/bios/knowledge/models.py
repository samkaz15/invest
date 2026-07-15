"""L3 domain records (MASTER_SYSTEM_DESIGN §5-§9).

These are the shapes the Event Store speaks. All are immutable records;
the store enforces the write-side invariants (evidence present, chain
exists) inside the insert transaction.
"""

from datetime import date, datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from bios.common.errors import BiosError, InvalidIdError
from bios.common.ids import IdKind, validate_id
from bios.common.labels import ChainStatus, EventConfidence, EventStatus, SourceTier
from bios.common.schema import BiosModel, BiosRecord
from bios.common.timeutil import TimePrecision, ensure_utc


def _vid(value: str, kind: IdKind) -> str:
    try:
        return validate_id(value, kind)
    except InvalidIdError as exc:
        raise ValueError(str(exc)) from exc


def _vutc(value: datetime) -> datetime:
    try:
        return ensure_utc(value)
    except BiosError as exc:
        raise ValueError(str(exc)) from exc


class EntityRecord(BiosRecord):
    entity_id: str
    kind: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    identifiers: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)
    confidence: str = "verified"

    @field_validator("entity_id")
    @classmethod
    def _eid(cls, v: str) -> str:
        return _vid(v, IdKind.ENTITY)


class ChainRecord(BiosRecord):
    chain_id: str
    title: str
    chain_type: str
    status: ChainStatus
    parent_chain_id: str | None = None
    started_at: date | None = None
    closed_at: date | None = None
    milestones: list[dict[str, Any]] = Field(default_factory=list)
    watch_points: list[str] = Field(default_factory=list)
    summary: str = ""

    @field_validator("chain_id")
    @classmethod
    def _cid(cls, v: str) -> str:
        return _vid(v, IdKind.CHAIN)


class EvidenceRecord(BiosRecord):
    evidence_id: str
    source_id: str
    tier: SourceTier
    retrieved_at: datetime
    raw_item_id: str | None = None
    url: str | None = None
    archived_url: str | None = None
    quote: str = ""
    published_at: datetime | None = None

    @field_validator("evidence_id")
    @classmethod
    def _evid(cls, v: str) -> str:
        return _vid(v, IdKind.EVIDENCE)

    @field_validator("retrieved_at")
    @classmethod
    def _rutc(cls, v: datetime) -> datetime:
        return _vutc(v)


class Participation(BiosModel):
    entity_id: str
    role: str  # actor | target | counterparty | venue | affected | mentioned
    detail: str = ""


class EventRecord(BiosRecord):
    event_id: str
    type: str  # domain.category.type (validated against taxonomy at the store)
    title: str
    summary_fact: str
    occurred_at: datetime
    known_at: datetime
    time_precision: TimePrecision
    confidence: EventConfidence
    status: EventStatus = EventStatus.CONFIRMED
    supersedes: str | None = None
    ended_at: datetime | None = None
    chain_id: str | None = None
    magnitude_initial: int | None = Field(default=None, ge=1, le=5)
    assets: list[dict[str, Any]] = Field(default_factory=list)  # {asset_id, relevance}
    tags: list[str] = Field(default_factory=list)
    curation: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = 2

    @field_validator("event_id")
    @classmethod
    def _evtid(cls, v: str) -> str:
        return _vid(v, IdKind.EVENT)

    @field_validator("occurred_at", "known_at", "ended_at")
    @classmethod
    def _tutc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else _vutc(v)

    @model_validator(mode="after")
    def _known_not_far_before_occurred(self) -> "EventRecord":
        if (self.known_at - self.occurred_at).total_seconds() < -86400:
            raise ValueError("known_at cannot precede occurred_at by more than a day")
        return self


class RelationRecord(BiosRecord):
    from_event: str
    to_event: str
    rel_type: str
    created_by: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_id: str | None = None

    @model_validator(mode="after")
    def _causal_needs_evidence(self) -> "RelationRecord":
        if self.rel_type in ("TRIGGERED_BY", "CAUSED_BY_BG") and (
            self.evidence_id is None or self.confidence is None
        ):
            raise ValueError(f"{self.rel_type} requires evidence_id and confidence (MSD §6.3)")
        return self
