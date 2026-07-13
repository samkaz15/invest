"""Exception hierarchy. Every BIOS-raised error derives from BiosError."""


class BiosError(Exception):
    """Base class for all BIOS errors."""


class ConfigError(BiosError):
    """Configuration file missing, unparsable, or failing schema validation."""


class InvalidIdError(BiosError):
    """Identifier does not conform to the ID conventions (bios.common.ids)."""


class AuditWriteError(BiosError):
    """An audit record could not be durably appended.

    Audit writes are load-bearing (Constitution Art.6): callers must treat
    this as a hard failure, never swallow it.
    """
