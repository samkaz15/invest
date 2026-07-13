"""Config loader tests — including validation of the real config/ tree."""

from pathlib import Path

import pytest

from bios.common import ConfigError
from bios.config import EventTaxonomy, load_config
from bios.config.loader import load_model

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config"


def test_real_config_tree_is_valid() -> None:
    """The committed config/ tree must always load. This is the guard that
    keeps 'one YAML line' taxonomy edits honest."""
    root = load_config(REPO_CONFIG)
    assert "ent_asset_btc" in root.assets
    assert root.assets["ent_asset_btc"].asset_class == "crypto"
    assert "TRIGGERED_BY" in root.relationships.event_event
    assert "actor" in root.relationships.participation_roles
    assert "asset" in root.entities.kinds
    assert "default" in root.scoring.weight_sets
    # every scoring dimension name is snake_case and includes anomaly cap rule
    assert root.scoring.anomaly_points_cap <= 5
    # source registry + pipelines cross-checked
    assert "src_sec_press_rss" in root.sources
    assert root.sources["src_sec_press_rss"].tier == 1
    assert all(j.source_id in root.sources for j in root.pipelines.jobs if j.task == "collect")


def test_event_types_are_three_levels() -> None:
    root = load_config(REPO_CONFIG)
    for t in root.events.types:
        assert len(t.split(".")) == 3, t
    assert {"onchain", "macro", "supply", "demand"} <= root.events.domains()


def test_typo_in_yaml_fails_loudly(tmp_path: Path) -> None:
    bad = tmp_path / "events.yaml"
    bad.write_text("typs: [a.b.c]\n", encoding="utf-8")  # typo'd key
    with pytest.raises(ConfigError, match="invalid config"):
        load_model(bad, EventTaxonomy)


def test_bad_event_type_shape_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "events.yaml"
    bad.write_text("types: ['onchain.only_two']\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"domain\.category\.type"):
        load_model(bad, EventTaxonomy)


def test_missing_file_is_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_model(tmp_path / "nope.yaml", EventTaxonomy)


def test_missing_assets_dir_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="assets"):
        load_config(tmp_path)
