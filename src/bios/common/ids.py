"""Identifier conventions (MASTER_SYSTEM_DESIGN §5-§13).

Two ID families:

* Opaque IDs — ``<prefix>_<millis-hex><random-hex>`` via :func:`new_id`.
  Time-prefixed so lexicographic order ≈ creation order (useful for
  append-only tables and log files).
* Human-readable event IDs — ``evt_<YYYY-MM-DD>_<slug>`` via
  :func:`make_event_id`, per the design's requirement that events are
  recognizable in reviews and reports.
"""

import re
import secrets
import time
import unicodedata
from enum import StrEnum

from bios.common.errors import InvalidIdError


class IdKind(StrEnum):
    """Registered ID prefixes. Adding a kind is append-only."""

    RAW_ITEM = "raw"
    SOURCE = "src"
    EVIDENCE = "evd"
    EVENT = "evt"
    ENTITY = "ent"
    CHAIN = "chain"
    PATTERN = "pat"
    OVERHANG = "ovh"
    ANOMALY = "anm"
    SCENARIO_SET = "scn"
    DECISION = "dcs"
    SCORE_CARD = "sc"
    AGENT_RUN = "run"


_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_EVENT_ID_RE = re.compile(r"^evt_\d{4}-\d{2}-\d{2}_[a-z0-9]+(?:-[a-z0-9]+)*$")
_OPAQUE_ID_RE = re.compile(r"^[a-z]+_[0-9a-f]{17}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id(kind: IdKind) -> str:
    """Return a new opaque ID: prefix + 11 hex millis + 6 hex random."""
    millis = int(time.time() * 1000)
    return f"{kind.value}_{millis:011x}{secrets.token_hex(3)}"


def slugify(text: str) -> str:
    """Reduce arbitrary text to a lowercase ascii slug (for event IDs)."""
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if not slug:
        raise InvalidIdError(f"cannot derive a slug from {text!r}")
    return slug


def make_event_id(date: str, slug: str) -> str:
    """Build a human-readable event ID, e.g. ``evt_2024-01-10_etf-approval``.

    ``date`` is the event's *occurred_at* calendar date (UTC, YYYY-MM-DD).
    """
    if not _DATE_RE.match(date):
        raise InvalidIdError(f"event date must be YYYY-MM-DD, got {date!r}")
    if not _SLUG_RE.match(slug):
        slug = slugify(slug)
    return f"evt_{date}_{slug}"


def validate_id(value: str, kind: IdKind) -> str:
    """Validate ``value`` against the conventions for ``kind``; return it.

    Raises :class:`InvalidIdError` on mismatch. Used by schema validators so
    that malformed references never enter a store.
    """
    prefix = f"{kind.value}_"
    if not value.startswith(prefix):
        raise InvalidIdError(f"{value!r} does not carry prefix {prefix!r}")
    if kind is IdKind.EVENT:
        if not _EVENT_ID_RE.match(value):
            raise InvalidIdError(f"{value!r} is not a valid event id (evt_<date>_<slug>)")
    elif not _OPAQUE_ID_RE.match(value):
        raise InvalidIdError(f"{value!r} is not a valid opaque {kind.name} id")
    return value
