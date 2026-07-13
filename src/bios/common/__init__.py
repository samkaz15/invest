"""Cross-layer vocabulary and primitives.

This package may not import from any other bios subpackage — it is the
root of the dependency graph.
"""

from bios.common.errors import AuditWriteError, BiosError, ConfigError, InvalidIdError
from bios.common.ids import IdKind, make_event_id, new_id, validate_id
from bios.common.labels import (
    Action,
    ChainStatus,
    ClaimLabel,
    EventConfidence,
    EventStatus,
    RunStatus,
    SourceTier,
    Stance,
)
from bios.common.schema import BiosModel, BiosRecord
from bios.common.timeutil import TimePrecision, ensure_utc, parse_utc, utc_now

__all__ = [
    "Action",
    "AuditWriteError",
    "BiosError",
    "BiosModel",
    "BiosRecord",
    "ChainStatus",
    "ClaimLabel",
    "ConfigError",
    "EventConfidence",
    "EventStatus",
    "IdKind",
    "InvalidIdError",
    "RunStatus",
    "SourceTier",
    "Stance",
    "TimePrecision",
    "ensure_utc",
    "make_event_id",
    "new_id",
    "parse_utc",
    "utc_now",
    "validate_id",
]
