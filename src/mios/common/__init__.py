"""Cross-layer vocabulary and primitives.

This package may not import from any other mios subpackage — it is the
root of the dependency graph (enforced by tests/unit/test_architecture.py).
"""

from mios.common.errors import AuditWriteError, ConfigError, InvalidIdError, MiosError
from mios.common.ids import (
    DATED_KINDS,
    OPAQUE_KINDS,
    SLUG_KINDS,
    IdKind,
    make_dated_id,
    make_event_id,
    make_slug_id,
    new_id,
    pydantic_id_validator,
    validate_id,
)
from mios.common.labels import (
    ChainStatus,
    ClaimLabel,
    Country,
    Dimension,
    Direction,
    EventConfidence,
    EventStatus,
    Frequency,
    RunStatus,
    SourceTier,
    Stance,
)
from mios.common.schema import MiosModel, MiosRecord
from mios.common.timeutil import TimePrecision, ensure_utc, parse_utc, utc_now

__all__ = [
    "DATED_KINDS",
    "OPAQUE_KINDS",
    "SLUG_KINDS",
    "AuditWriteError",
    "ChainStatus",
    "ClaimLabel",
    "ConfigError",
    "Country",
    "Dimension",
    "Direction",
    "EventConfidence",
    "EventStatus",
    "Frequency",
    "IdKind",
    "InvalidIdError",
    "MiosError",
    "MiosModel",
    "MiosRecord",
    "RunStatus",
    "SourceTier",
    "Stance",
    "TimePrecision",
    "ensure_utc",
    "make_dated_id",
    "make_event_id",
    "make_slug_id",
    "new_id",
    "parse_utc",
    "pydantic_id_validator",
    "utc_now",
    "validate_id",
]
