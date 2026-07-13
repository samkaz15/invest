"""Cross-layer vocabulary and primitives.

This package may not import from any other bios subpackage — it is the
root of the dependency graph (enforced by tests/unit/test_architecture.py).
"""

from bios.common.errors import AuditWriteError, BiosError, ConfigError, InvalidIdError
from bios.common.ids import (
    DATED_KINDS,
    OPAQUE_KINDS,
    SLUG_KINDS,
    IdKind,
    make_dated_id,
    make_event_id,
    make_slug_id,
    new_id,
    validate_id,
)
from bios.common.labels import (
    Action,
    ChainStatus,
    ClaimLabel,
    Dimension,
    EventConfidence,
    EventStatus,
    RunStatus,
    SourceTier,
    Stance,
)
from bios.common.schema import BiosModel, BiosRecord
from bios.common.timeutil import TimePrecision, ensure_utc, parse_utc, utc_now

__all__ = [
    "DATED_KINDS",
    "OPAQUE_KINDS",
    "SLUG_KINDS",
    "Action",
    "AuditWriteError",
    "BiosError",
    "BiosModel",
    "BiosRecord",
    "ChainStatus",
    "ClaimLabel",
    "ConfigError",
    "Dimension",
    "EventConfidence",
    "EventStatus",
    "IdKind",
    "InvalidIdError",
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
    "utc_now",
    "validate_id",
]
