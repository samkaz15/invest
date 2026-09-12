"""Load and validate the ``config/`` YAML tree into typed objects."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from mios.common.errors import ConfigError
from mios.config.analysis import AnalysisConfig
from mios.config.external import ExternalConfig
from mios.config.forecast import ForecastConfig
from mios.config.models import (
    AssetConfig,
    EntityTaxonomy,
    EventTaxonomy,
    PipelinesConfig,
    RelationshipTaxonomy,
    ScoringConfig,
    SourceSpec,
)
from mios.config.series import SeriesRegistry


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"unparsable YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"top level of {path} must be a mapping")
    return data


def load_model[M: BaseModel](path: Path, model: type[M]) -> M:
    """Read one YAML file into ``model``; wrap all failures in ConfigError."""
    try:
        return model.model_validate(_read_yaml(path))
    except ValidationError as exc:
        raise ConfigError(f"invalid config {path}:\n{exc}") from exc


@dataclass(frozen=True)
class ConfigRoot:
    """The fully-validated configuration tree."""

    events: EventTaxonomy
    entities: EntityTaxonomy
    relationships: RelationshipTaxonomy
    scoring: ScoringConfig
    assets: dict[str, AssetConfig]  # keyed by asset_id
    sources: dict[str, SourceSpec]  # keyed by source_id (the machine-readable source registry)
    series: SeriesRegistry
    forecast: ForecastConfig
    external: ExternalConfig
    analysis: AnalysisConfig
    pipelines: PipelinesConfig


def load_config(config_dir: Path) -> ConfigRoot:
    """Load the whole tree. Any invalid file aborts startup — a system whose
    taxonomy failed to load must not ingest data half-configured."""
    assets: dict[str, AssetConfig] = {}
    assets_dir = config_dir / "assets"
    if not assets_dir.is_dir():
        raise ConfigError(f"missing assets directory: {assets_dir}")
    for path in sorted(assets_dir.glob("*.yaml")):
        asset = load_model(path, AssetConfig)
        if asset.asset_id in assets:
            raise ConfigError(f"duplicate asset_id {asset.asset_id!r} in {path}")
        assets[asset.asset_id] = asset
    if not assets:
        raise ConfigError(f"no assets defined under {assets_dir}")

    sources: dict[str, SourceSpec] = {}
    sources_dir = config_dir / "sources"
    if sources_dir.is_dir():
        for path in sorted(sources_dir.glob("*.yaml")):
            spec = load_model(path, SourceSpec)
            if spec.source_id in sources:
                raise ConfigError(f"duplicate source_id {spec.source_id!r} in {path}")
            sources[spec.source_id] = spec

    series = load_model(config_dir / "series.yaml", SeriesRegistry)
    for series_spec in series.series:
        if series_spec.source_id not in sources:
            raise ConfigError(
                f"series {series_spec.series_id!r} references unknown "
                f"source {series_spec.source_id!r}"
            )

    forecast = load_model(config_dir / "forecast.yaml", ForecastConfig)
    known_series = {s.series_id for s in series.series}
    for target in forecast.targets:
        unknown = [
            sid
            for sid in [target.series_id, *(d.series_id for d in target.drivers)]
            if sid not in known_series
        ]
        if unknown:
            raise ConfigError(
                f"forecast target {target.series_id!r} references unregistered "
                f"series {sorted(unknown)}"
            )

    external = load_model(config_dir / "external.yaml", ExternalConfig)
    forecast_targets = {t.series_id for t in forecast.targets}
    for provider in external.providers:
        if provider.provider_id not in sources:
            raise ConfigError(
                f"external provider {provider.provider_id!r} has no source file under "
                f"{sources_dir} — it has to be collectable before it can be compared against"
            )
        unknown = [
            t.target_series_id
            for t in provider.targets
            if t.target_series_id not in forecast_targets
        ]
        if unknown:
            raise ConfigError(
                f"external provider {provider.provider_id!r} forecasts {sorted(unknown)}, "
                "which MIOS does not itself forecast — there would be nothing to compare it to"
            )
    # `uncovered` is what the scoreboard cannot benchmark. Naming a target
    # that is both covered and uncovered, or one that is not forecast at all,
    # would make that declaration misleading rather than incomplete.
    covered = {t.target_series_id for p in external.providers for t in p.targets}
    for series_id in external.uncovered:
        if series_id not in forecast_targets:
            raise ConfigError(
                f"external.uncovered names {series_id!r}, which is not a forecast target"
            )
        if series_id in covered:
            raise ConfigError(f"external.uncovered names {series_id!r}, but a provider covers it")

    analysis = load_model(config_dir / "analysis.yaml", AnalysisConfig)
    for dimension in analysis.dimensions:
        unknown = [s.series_id for s in dimension.signals if s.series_id not in known_series]
        if unknown:
            raise ConfigError(
                f"dimension {dimension.dimension!r} references unregistered "
                f"series {sorted(unknown)}"
            )
    known_assets = set(assets)
    for view in analysis.views:
        if view.asset_id not in known_assets:
            raise ConfigError(f"view {view.view_id!r} references unknown asset {view.asset_id!r}")

    pipelines = load_model(config_dir / "pipelines.yaml", PipelinesConfig)
    for job in pipelines.jobs:
        if job.task == "collect":
            if job.source_id is None:
                raise ConfigError(f"job {job.job_id!r}: collect jobs need source_id")
            if job.source_id not in sources:
                raise ConfigError(f"job {job.job_id!r} references unknown source {job.source_id!r}")

    return ConfigRoot(
        sources=sources,
        series=series,
        forecast=forecast,
        external=external,
        analysis=analysis,
        pipelines=pipelines,
        events=load_model(config_dir / "taxonomy" / "events.yaml", EventTaxonomy),
        entities=load_model(config_dir / "taxonomy" / "entities.yaml", EntityTaxonomy),
        relationships=load_model(
            config_dir / "taxonomy" / "relationships.yaml", RelationshipTaxonomy
        ),
        scoring=load_model(config_dir / "scoring.yaml", ScoringConfig),
        assets=assets,
    )
