"""Config loader tests — including validation of the real config/ tree."""

from pathlib import Path

import pytest

from mios.common import ConfigError
from mios.config import EventTaxonomy, load_config
from mios.config.loader import load_model

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config"


def test_real_config_tree_is_valid() -> None:
    """The committed config/ tree must always load. This is the guard that
    keeps 'one YAML line' taxonomy edits honest."""
    root = load_config(REPO_CONFIG)
    # Both analysed assets are configuration, never a code assumption.
    assert {"ent_asset_xauusd", "ent_asset_usdjpy"} <= set(root.assets)
    assert root.assets["ent_asset_xauusd"].symbol == "XAU/USD"
    assert root.assets["ent_asset_usdjpy"].asset_class == "fx"
    assert "TRIGGERED_BY" in root.relationships.event_event
    assert "actor" in root.relationships.participation_roles
    assert "economic_indicator" in root.entities.kinds
    assert "default" in root.scoring.weight_sets
    # Official statistics outrank redistributors: the CPI source is tier 1.
    assert root.sources["src_fred_cpiaucsl"].tier == 1
    # Every collect job points at a source that actually exists.
    assert all(j.source_id in root.sources for j in root.pipelines.jobs if j.task == "collect")


def test_every_series_resolves_to_a_source_and_is_reachable_by_a_job() -> None:
    """A series whose source nobody collects is data that never arrives.

    The loader already refuses an unknown source_id; this covers the other
    half, where the source exists but no scheduled job ever fetches it.
    """
    root = load_config(REPO_CONFIG)
    scheduled = {j.source_id for j in root.pipelines.jobs if j.task == "collect"}
    orphans = sorted({s.series_id for s in root.series.series if s.source_id not in scheduled})
    assert not orphans, f"series with no collect job: {orphans}"


def test_price_series_are_not_marked_revisable() -> None:
    """Guards the distinction the whole vintage design rests on.

    A spot price is published once; an economic statistic is restated. Only
    the second kind needs its history preserved, and mislabelling the second
    as the first is how look-ahead bias gets in.
    """
    root = load_config(REPO_CONFIG)
    for spec in root.series.series:
        if spec.category in ("fx", "commodity", "risk"):
            assert not spec.revisable, spec.series_id
        if spec.category in ("inflation", "employment", "growth"):
            assert spec.revisable, f"{spec.series_id}: official statistics get revised"


def test_event_types_are_three_levels() -> None:
    root = load_config(REPO_CONFIG)
    for t in root.events.types:
        assert len(t.split(".")) == 3, t
    assert {"release", "policy", "market", "forecast", "context"} <= root.events.domains()


def test_typo_in_yaml_fails_loudly(tmp_path: Path) -> None:
    bad = tmp_path / "events.yaml"
    bad.write_text("typs: [a.b.c]\n", encoding="utf-8")  # typo'd key
    with pytest.raises(ConfigError, match="invalid config"):
        load_model(bad, EventTaxonomy)


def test_bad_event_type_shape_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "events.yaml"
    bad.write_text("types: ['release.only_two']\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"domain\.category\.type"):
        load_model(bad, EventTaxonomy)


def test_missing_file_is_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_model(tmp_path / "nope.yaml", EventTaxonomy)


def test_missing_assets_dir_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="assets"):
        load_config(tmp_path)


# --------------------------------------------- institutional forecast config


def test_every_forecast_target_is_either_benchmarked_or_declared_uncovered() -> None:
    """The declaration that keeps the scoreboard from reading as complete.

    Two of the four targets have no free institutional forecast. A
    head-to-head table covering only the other two looks like the whole
    picture unless the gap is named, so `uncovered` is required and is
    checked against the target list here rather than trusted.
    """
    root = load_config(REPO_CONFIG)
    targets = {t.series_id for t in root.forecast.targets}
    covered = {t.target_series_id for p in root.external.providers for t in p.targets}
    assert covered | set(root.external.uncovered) == targets, (
        "every forecast target must be either benchmarked or explicitly declared uncovered"
    )
    assert not covered & set(root.external.uncovered)


def test_every_external_provider_is_also_a_collectable_source() -> None:
    """A provider with no source file is a benchmark nothing ever fetches."""
    root = load_config(REPO_CONFIG)
    for provider in root.external.providers:
        assert provider.provider_id in root.sources


def test_an_external_provider_must_state_its_conversion_and_its_url() -> None:
    """Both are load-bearing.

    Without the scale, a figure published in percent is compared against a
    fraction and the provider looks wrong by two orders of magnitude — which
    reads as a finding rather than as a bug. Without the URL, a stored
    forecast is a number nobody can go and check (指示書 §26).
    """
    root = load_config(REPO_CONFIG)
    for provider in root.external.providers:
        assert provider.source_url.startswith("https://")
        for target in provider.targets:
            assert target.scale > 0
            assert target.raw_unit
