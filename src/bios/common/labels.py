"""Shared vocabulary enums (Constitution Art.4-5, MASTER_SYSTEM_DESIGN §8).

These are the words the whole system speaks. Renaming a member is a
breaking change and requires an ADR; adding members is allowed.
"""

from enum import IntEnum, StrEnum


class ClaimLabel(StrEnum):
    """Mandatory label on every claim (Constitution Art.4)."""

    FACT = "FACT"  # verified against tier-1/2 evidence; evidence id required
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
    """Source trust tiers (DATA_SOURCE_REGISTRY.md). Lower is more trusted."""

    PRIMARY = 1  # official filings, court documents, on-chain data
    QUASI_PRIMARY = 2  # first-party statements, press releases
    MAJOR_PRESS = 3  # Reuters, Bloomberg, WSJ, Nikkei
    SECONDARY = 4  # industry media, analyst commentary, social media


class Stance(StrEnum):
    """Directional read of an analysis."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class Action(StrEnum):
    """The only decision vocabulary BIOS may emit (Constitution Art.1)."""

    BUY = "BUY"
    WAIT = "WAIT"
    TAKE_PROFIT = "TAKE_PROFIT"


class Dimension(StrEnum):
    """Analysis dimensions (INTELLIGENCE_ENGINE_SPECIFICATION §1.3)."""

    NEWS = "news"
    SUPPLY = "supply"
    DEMAND = "demand"
    ONCHAIN = "onchain"
    DERIVATIVES = "derivatives"
    MACRO = "macro"
    ANOMALY = "anomaly"


class RunStatus(StrEnum):
    """Outcome of an agent/pipeline run (audit log)."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    DEGRADED = "degraded"
