"""Shared vocabulary enums.

These are the words the whole system speaks. Renaming a member is a
breaking change and requires an ADR; adding members is allowed.
"""

from enum import IntEnum, StrEnum


class ClaimLabel(StrEnum):
    """Mandatory label on every claim.

    The point is that a reader can always tell a measurement from a
    reading of one. An LLM may produce INFERENCE text; it may never
    produce a FACT number.
    """

    FACT = "FACT"  # measured value from a registered source; evidence id required
    REPORTED = "REPORTED"  # reported but not primary-verified; source required
    INFERENCE = "INFERENCE"  # system inference; reasoning required


class EventConfidence(StrEnum):
    """Fact-level confidence of an event record."""

    VERIFIED = "verified"
    REPORTED = "reported"
    DISPUTED = "disputed"


class EventStatus(StrEnum):
    """Lifecycle of an event record (append-only; corrections supersede)."""

    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    RETRACTED = "retracted"


class ChainStatus(StrEnum):
    """Lifecycle of an event chain."""

    ACTIVE = "active"
    DORMANT = "dormant"
    CLOSED = "closed"


class SourceTier(IntEnum):
    """Source trust tiers. Lower is more trusted.

    Tier 1 is the statistical agency or central bank that publishes the
    number. Tier 2 is a redistributor of it. A Tier 3/4 report of a number
    never overrides the Tier 1 print.
    """

    OFFICIAL = 1  # BLS, BEA, Census, DOL, Federal Reserve, US Treasury, BOJ, e-Stat, MOF
    DATA_PROVIDER = 2  # major financial data providers redistributing official/market data
    MAJOR_MEDIA = 3  # Reuters, Bloomberg, WSJ, Nikkei
    OTHER_MEDIA = 4  # other media and commentary; never a primary datum


class Direction(StrEnum):
    """Which way a release or a driver is expected to break.

    Replaces the old BUY/WAIT/TAKE_PROFIT vocabulary: MIOS forecasts data,
    it does not advise trades.
    """

    UPSIDE = "upside"  # above consensus / higher than previous
    INLINE = "inline"
    DOWNSIDE = "downside"


class Stance(StrEnum):
    """Directional read of a macro analysis for an asset."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class Dimension(StrEnum):
    """Macro analysis dimensions.

    Deliberately few (docs/REPOSITORY_AUDIT.md §13): a dimension exists only
    when something measurable feeds it. Adding one means adding its inputs.
    """

    GROWTH = "growth"
    INFLATION = "inflation"
    LABOR = "labor"
    FED = "fed"
    BOJ = "boj"
    RATES = "rates"
    FX = "fx"
    RISK = "risk"


class Country(StrEnum):
    """Jurisdictions MIOS tracks."""

    US = "US"
    JP = "JP"
    EA = "EA"  # euro area
    CN = "CN"
    GLOBAL = "GLOBAL"


class Frequency(StrEnum):
    """Publication frequency of a data series."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    IRREGULAR = "irregular"  # FOMC, BOJ meetings


class RunStatus(StrEnum):
    """Outcome of a pipeline run (audit log)."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    DEGRADED = "degraded"
