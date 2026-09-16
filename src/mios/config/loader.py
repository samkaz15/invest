"""Load and validate the ``config/`` YAML tree into typed objects."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from mios.common.errors import ConfigError
from mios.config.analysis import AnalysisConfig
from mios.config.calendar import UNCATEGORISED, CalendarConfig
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
    calendar: CalendarConfig
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

    calendar = load_model(config_dir / "calendar.yaml", CalendarConfig)
    for watched in calendar.watch:
        unknown = [s for s in watched.series if s not in known_series]
        if unknown:
            raise ConfigError(
                f"calendar entry {watched.release_name!r} references unregistered "
                f"series {sorted(unknown)}"
            )
    names = [w.release_name for w in calendar.watch]
    duplicate = {n for n in names if names.count(n) > 1}
    if duplicate:
        raise ConfigError(f"duplicate calendar release_name {sorted(duplicate)}")

    analysis = load_model(config_dir / "analysis.yaml", AnalysisConfig)
    for dimension in analysis.dimensions:
        unknown = [s.series_id for s in dimension.signals if s.series_id not in known_series]
        if unknown:
            raise ConfigError(
                f"dimension {dimension.dimension!r} references unregistered "
                f"series {sorted(unknown)}"
            )
    known_assets = set(assets)
    known_dimensions = {d.dimension for d in analysis.dimensions}
    for view in analysis.views:
        if view.asset_id not in known_assets:
            raise ConfigError(f"view {view.view_id!r} references unknown asset {view.asset_id!r}")
        # A link to a dimension that no longer exists would not raise: the
        # view would simply score it as a gap and read as a slightly less
        # confident version of itself, forever. Removing the BOJ dimension
        # (ADR-015) is exactly the change that produces this, so it is
        # caught at load rather than left to be noticed.
        dangling = [link.dimension for link in view.links if link.dimension not in known_dimensions]
        if dangling:
            raise ConfigError(
                f"view {view.view_id!r} links to dimensions that do not exist: {sorted(dangling)}"
            )

    pipelines = load_model(config_dir / "pipelines.yaml", PipelinesConfig)
    for job in pipelines.jobs:
        if job.task == "collect":
            if job.source_id is None:
                raise ConfigError(f"job {job.job_id!r}: collect jobs need source_id")
            if job.source_id not in sources:
                raise ConfigError(f"job {job.job_id!r} references unknown source {job.source_id!r}")

    events = load_model(config_dir / "taxonomy" / "events.yaml", EventTaxonomy)
    unknown_types = sorted(
        {w.event_type for w in calendar.watch} - set(events.types) - {UNCATEGORISED}
    )
    if unknown_types:
        raise ConfigError(f"calendar uses event types absent from the taxonomy: {unknown_types}")

    return ConfigRoot(
        sources=sources,
        series=series,
        forecast=forecast,
        calendar=calendar,
        analysis=analysis,
        pipelines=pipelines,
        events=events,
        entities=load_model(config_dir / "taxonomy" / "entities.yaml", EntityTaxonomy),
        relationships=load_model(
            config_dir / "taxonomy" / "relationships.yaml", RelationshipTaxonomy
        ),
        scoring=load_model(config_dir / "scoring.yaml", ScoringConfig),
        assets=assets,
    )
