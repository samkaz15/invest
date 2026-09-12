"""Exception hierarchy. Every BIOS-raised error derives from MiosError."""


class MiosError(Exception):
    """Base class for all BIOS errors."""


class ConfigError(MiosError):
    """Configuration file missing, unparsable, or failing schema validation."""


class InvalidIdError(MiosError):
    """Identifier does not conform to the ID conventions (mios.common.ids)."""


class AuditWriteError(MiosError):
    """An audit record could not be durably appended.

    Audit writes are load-bearing (Constitution Art.6): callers must treat
    this as a hard failure, never swallow it.
    """
