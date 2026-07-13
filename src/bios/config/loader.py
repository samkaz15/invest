"""Load and validate the ``config/`` YAML tree into typed objects."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from bios.common.errors import ConfigError
from bios.config.models import (
    AgentsConfig,
    AssetConfig,
    EntityTaxonomy,
    EventTaxonomy,
    RelationshipTaxonomy,
    ScoringConfig,
)


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

    agents: AgentsConfig
    events: EventTaxonomy
    entities: EntityTaxonomy
    relationships: RelationshipTaxonomy
    scoring: ScoringConfig
    assets: dict[str, AssetConfig]  # keyed by asset_id


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

    return ConfigRoot(
        agents=load_model(config_dir / "agents.yaml", AgentsConfig),
        events=load_model(config_dir / "taxonomy" / "events.yaml", EventTaxonomy),
        entities=load_model(config_dir / "taxonomy" / "entities.yaml", EntityTaxonomy),
        relationships=load_model(
            config_dir / "taxonomy" / "relationships.yaml", RelationshipTaxonomy
        ),
        scoring=load_model(config_dir / "scoring.yaml", ScoringConfig),
        assets=assets,
    )
