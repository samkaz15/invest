"""Configuration layer (principle: behavior changes without code changes).

Behavior that must change without code changes — taxonomy, assets, sources,
schedules, weights — lives in YAML under ``config/`` and is loaded here into
typed, validated objects. Unknown keys are rejected (typos fail loudly).
"""

from mios.config.analysis import AnalysisConfig, AssetViewSpec, DimensionSpec
from mios.config.forecast import DriverSpec, ForecastConfig, TargetSpec
from mios.config.loader import ConfigRoot, load_config
from mios.config.models import (
    AssetConfig,
    EntityTaxonomy,
    EventTaxonomy,
    RelationshipTaxonomy,
    ScoringConfig,
    SourceSpec,
)
from mios.config.series import SeriesRegistry, SeriesSpec
from mios.config.settings import Settings

__all__ = [
    "AnalysisConfig",
    "AssetConfig",
    "AssetViewSpec",
    "ConfigRoot",
    "DimensionSpec",
    "DriverSpec",
    "EntityTaxonomy",
    "EventTaxonomy",
    "ForecastConfig",
    "RelationshipTaxonomy",
    "ScoringConfig",
    "SeriesRegistry",
    "SeriesSpec",
    "Settings",
    "SourceSpec",
    "TargetSpec",
    "load_config",
]
