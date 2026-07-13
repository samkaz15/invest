"""Pydantic base models.

Two bases, one distinction: is the object an append-only record or not?

* :class:`BiosModel` — mutable working object (config, in-flight state).
* :class:`BiosRecord` — immutable record. Anything persisted to an
  append-only store (events, evidence, decisions, audit entries) derives
  from this; correction happens by writing a superseding record, never by
  mutation (Constitution Art.3).

Both forbid unknown fields so typos fail loudly instead of being silently
dropped.
"""

from pydantic import BaseModel, ConfigDict


class BiosModel(BaseModel):
    """Base for mutable models."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BiosRecord(BaseModel):
    """Base for immutable, append-only records."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
