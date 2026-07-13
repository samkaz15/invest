"""Configuration layer (MASTER_SYSTEM_DESIGN §2.2 config/, principle P10).

Behavior that must change without code changes — models, budgets, taxonomy,
weights — lives in YAML under ``config/`` and is loaded here into typed,
validated objects. Unknown keys are rejected (typos fail loudly).
"""

from bios.config.loader import ConfigRoot, load_config
from bios.config.models import (
    AgentsConfig,
    AgentSpec,
    AssetConfig,
    EntityTaxonomy,
    EventTaxonomy,
    RelationshipTaxonomy,
    ScoringConfig,
)
from bios.config.settings import Settings

__all__ = [
    "AgentSpec",
    "AgentsConfig",
    "AssetConfig",
    "ConfigRoot",
    "EntityTaxonomy",
    "EventTaxonomy",
    "RelationshipTaxonomy",
    "ScoringConfig",
    "Settings",
    "load_config",
]
