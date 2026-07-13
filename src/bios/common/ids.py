"""Identifier conventions (MASTER_SYSTEM_DESIGN §5-§13).

Three ID families, matching how the design names things:

* **Opaque** — high-volume records nobody types by hand:
  ``raw_/evd_/run_`` + 11-hex millis + 6-hex random (sortable, collision-safe).
* **Slug** — master data humans read and write in YAML/reviews:
  ``ent_mtgox``, ``src_sec_press``, ``chain_mtgox``, ``pat_government_sale``.
* **Dated** — one-per-day or per-occurrence artifacts:
  ``evt_2024-01-10_etf-approval``, ``dcs_2026-07-14_btc``.

Persisted IDs must validate forever: these formats are compatibility
contracts. Changing them requires an ADR.
"""

import re
import secrets
import time
import unicodedata
from datetime import date
from enum import StrEnum

from bios.common.errors import InvalidIdError


class IdKind(StrEnum):
    """Registered ID prefixes. Adding a kind is append-only."""

    RAW_ITEM = "raw"
    EVIDENCE = "evd"
    AGENT_RUN = "run"
    SOURCE = "src"
    ENTITY = "ent"
    CHAIN = "chain"
    PATTERN = "pat"
    OVERHANG = "ovh"
    ANOMALY = "anm"
    EVENT = "evt"
    SCENARIO_SET = "scn"
    DECISION = "dcs"
    SCORE_CARD = "sc"


OPAQUE_KINDS = frozenset({IdKind.RAW_ITEM, IdKind.EVIDENCE, IdKind.AGENT_RUN})
SLUG_KINDS = frozenset(
    {IdKind.SOURCE, IdKind.ENTITY, IdKind.CHAIN, IdKind.PATTERN, IdKind.OVERHANG, IdKind.ANOMALY}
)
DATED_KINDS = frozenset({IdKind.EVENT, IdKind.SCENARIO_SET, IdKind.DECISION, IdKind.SCORE_CARD})

_OPAQUE_RE = re.compile(r"^[a-z]+_[0-9a-f]{17}$")
_SNAKE_SLUG_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_HYPHEN_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DATED_RE = re.compile(r"^[a-z]+_\d{4}-\d{2}-\d{2}_[a-z0-9]+(?:-[a-z0-9]+)*$")


def new_id(kind: IdKind) -> str:
    """New opaque ID (opaque kinds only): prefix + millis-hex + random-hex."""
    if kind not in OPAQUE_KINDS:
        raise InvalidIdError(f"{kind.name} ids are not opaque; use make_slug_id/make_dated_id")
    millis = int(time.time() * 1000)
    return f"{kind.value}_{millis:011x}{secrets.token_hex(3)}"


def slugify(text: str, separator: str = "-") -> str:
    """Reduce arbitrary text to a lowercase ascii slug."""
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", separator, normalized.lower()).strip(separator)
    if not slug:
        raise InvalidIdError(f"cannot derive a slug from {text!r}")
    return slug


def make_slug_id(kind: IdKind, name: str) -> str:
    """Human-readable master-data ID, e.g. ``make_slug_id(ENTITY, "Mt.Gox")``
    → ``ent_mt_gox``. Slug kinds use snake_case per the design examples."""
    if kind not in SLUG_KINDS:
        raise InvalidIdError(f"{kind.name} is not a slug kind")
    slug = name if _SNAKE_SLUG_RE.match(name) else slugify(name, separator="_")
    return f"{kind.value}_{slug}"


def make_dated_id(kind: IdKind, day: str, slug: str) -> str:
    """Dated ID, e.g. ``evt_2024-01-10_etf-approval``. ``day`` is the
    occurrence calendar date (UTC, YYYY-MM-DD) and must be a real date."""
    if kind not in DATED_KINDS:
        raise InvalidIdError(f"{kind.name} is not a dated kind")
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise InvalidIdError(f"invalid calendar date {day!r}: {exc}") from exc
    if not _HYPHEN_SLUG_RE.match(slug):
        slug = slugify(slug)
    return f"{kind.value}_{day}_{slug}"


def make_event_id(day: str, slug: str) -> str:
    """Shorthand for :func:`make_dated_id` with :attr:`IdKind.EVENT`."""
    return make_dated_id(IdKind.EVENT, day, slug)


def validate_id(value: str, kind: IdKind) -> str:
    """Validate ``value`` against the conventions for ``kind``; return it.

    Raises :class:`InvalidIdError` on mismatch. Schema validators call this
    so malformed references never enter a store.
    """
    prefix = f"{kind.value}_"
    if not value.startswith(prefix):
        raise InvalidIdError(f"{value!r} does not carry prefix {prefix!r}")
    rest = value[len(prefix) :]
    if kind in OPAQUE_KINDS:
        if not _OPAQUE_RE.match(value):
            raise InvalidIdError(f"{value!r} is not a valid opaque {kind.name} id")
    elif kind in SLUG_KINDS:
        if not _SNAKE_SLUG_RE.match(rest):
            raise InvalidIdError(f"{value!r} is not a valid {kind.name} slug id")
    else:  # dated
        if not _DATED_RE.match(value):
            raise InvalidIdError(f"{value!r} is not a valid dated {kind.name} id")
        date_part = rest.split("_", 1)[0]
        try:
            date.fromisoformat(date_part)
        except ValueError as exc:
            raise InvalidIdError(f"{value!r} has invalid date {date_part!r}") from exc
    return value
