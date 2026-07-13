"""Typed schemas for the YAML configuration tree.

Each model mirrors one file (or file family) under ``config/``. Validation
rules encode design invariants, e.g. event types are exactly three dotted
levels (MASTER_SYSTEM_DESIGN §7.3) and scoring weights are normalizable.
"""

import re

from pydantic import Field, field_validator, model_validator

from bios.common.labels import Dimension
from bios.common.schema import BiosModel

_EVENT_TYPE_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+$")
_NAME_RE = re.compile(r"^[a-z0-9_]+$")


class AgentSpec(BiosModel):
    """One agent's runtime envelope (model id lives here, never in code)."""

    model: str
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    timeout_seconds: int = Field(default=120, gt=0)
    prompt: str  # prompts/<agent>/<version>.md, relative to prompts/


class AgentsConfig(BiosModel):
    """config/agents.yaml"""

    agents: dict[str, AgentSpec]

    @field_validator("agents")
    @classmethod
    def _agent_names(cls, v: dict[str, AgentSpec]) -> dict[str, AgentSpec]:
        for name in v:
            if not _NAME_RE.match(name):
                raise ValueError(f"agent name must be snake_case: {name!r}")
        return v


class EventTaxonomy(BiosModel):
    """config/taxonomy/events.yaml — the closed list of event types."""

    types: list[str]

    @field_validator("types")
    @classmethod
    def _three_levels(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("duplicate event types")
        for t in v:
            if not _EVENT_TYPE_RE.match(t):
                raise ValueError(f"event type must be domain.category.type: {t!r}")
        return v

    def domains(self) -> set[str]:
        return {t.split(".", 1)[0] for t in self.types}


class EntityTaxonomy(BiosModel):
    """config/taxonomy/entities.yaml — registered entity kinds."""

    kinds: dict[str, str]  # kind -> one-line description

    @field_validator("kinds")
    @classmethod
    def _kind_names(cls, v: dict[str, str]) -> dict[str, str]:
        for kind in v:
            if not _NAME_RE.match(kind):
                raise ValueError(f"entity kind must be snake_case: {kind!r}")
        return v


class RelationshipTaxonomy(BiosModel):
    """config/taxonomy/relationships.yaml — the three edge classes (MSD §6)."""

    entity_entity: dict[str, str]  # rel_type -> description (class A)
    participation_roles: dict[str, str]  # role -> description (class B)
    event_event: dict[str, str]  # REL_TYPE -> description (class C)

    @model_validator(mode="after")
    def _casing(self) -> "RelationshipTaxonomy":
        for name in {**self.entity_entity, **self.participation_roles}:
            if not _NAME_RE.match(name):
                raise ValueError(f"relation/role must be snake_case: {name!r}")
        for name in self.event_event:
            if not re.match(r"^[A-Z0-9_]+$", name):
                raise ValueError(f"event-event rel_type must be UPPER_SNAKE: {name!r}")
        return self


class AssetConfig(BiosModel):
    """config/assets/<asset>.yaml — one tradable asset (P9: BTC is data)."""

    asset_id: str
    name: str
    asset_class: str  # crypto | equity | fx | commodity | bond
    metrics: list[str] = Field(default_factory=list)  # asset-specific snapshot metrics


class ScoringConfig(BiosModel):
    """config/scoring.yaml — dimension weights and caps (IES §11.3)."""

    weights_version: str
    anomaly_points_cap: int = Field(default=5, ge=0)
    weight_sets: dict[str, dict[str, float]]  # phase name -> dimension -> weight

    @model_validator(mode="after")
    def _weights_positive(self) -> "ScoringConfig":
        if "default" not in self.weight_sets:
            raise ValueError("weight_sets must define a 'default' set")
        known = {d.value for d in Dimension}
        for phase, weights in self.weight_sets.items():
            if not weights:
                raise ValueError(f"empty weight set: {phase!r}")
            for dim, w in weights.items():
                if dim not in known:
                    raise ValueError(f"unknown dimension {phase}.{dim!r} (known: {sorted(known)})")
                if w < 0:
                    raise ValueError(f"negative weight {phase}.{dim}={w}")
        return self
