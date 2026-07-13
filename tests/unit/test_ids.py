"""ID convention tests (bios.common.ids) — three families."""

import pytest

from bios.common import (
    DATED_KINDS,
    OPAQUE_KINDS,
    SLUG_KINDS,
    IdKind,
    InvalidIdError,
    make_dated_id,
    make_event_id,
    make_slug_id,
    new_id,
    validate_id,
)
from bios.common.ids import slugify


def test_families_cover_all_kinds() -> None:
    assert set(IdKind) == OPAQUE_KINDS | SLUG_KINDS | DATED_KINDS
    assert not (OPAQUE_KINDS & SLUG_KINDS) and not (SLUG_KINDS & DATED_KINDS)


def test_opaque_ids_validate_and_sort() -> None:
    for kind in OPAQUE_KINDS:
        assert validate_id(new_id(kind), kind)
    ids = [new_id(IdKind.RAW_ITEM) for _ in range(200)]
    assert len(set(ids)) == 200
    assert all(i > "raw_00000000000abcdef" for i in ids)  # time-prefixed ordering


def test_new_id_refuses_non_opaque_kinds() -> None:
    with pytest.raises(InvalidIdError):
        new_id(IdKind.ENTITY)


def test_slug_ids_match_design_examples() -> None:
    # Human-readable master data ids straight from MASTER_SYSTEM_DESIGN
    assert validate_id("ent_mtgox", IdKind.ENTITY)
    assert validate_id("ent_asset_btc", IdKind.ENTITY)
    assert validate_id("src_sec_press", IdKind.SOURCE)
    assert validate_id("chain_mtgox", IdKind.CHAIN)
    assert validate_id("pat_government_sale", IdKind.PATTERN)
    assert make_slug_id(IdKind.ENTITY, "Mt.Gox") == "ent_mt_gox"
    with pytest.raises(InvalidIdError):
        validate_id("ent_MtGox", IdKind.ENTITY)  # uppercase forbidden


def test_dated_ids_match_design_examples() -> None:
    assert make_event_id("2024-01-10", "ETF Approval!") == "evt_2024-01-10_etf-approval"
    assert make_dated_id(IdKind.DECISION, "2026-07-14", "btc") == "dcs_2026-07-14_btc"
    assert validate_id("scn_2026-07-14_btc", IdKind.SCENARIO_SET)
    with pytest.raises(InvalidIdError):
        make_event_id("2024-13-45", "impossible-date")
    with pytest.raises(InvalidIdError):
        validate_id("evt_2024-13-45_bad", IdKind.EVENT)


def test_validate_rejects_cross_family_shapes() -> None:
    with pytest.raises(InvalidIdError):
        validate_id("evd_not-hex-at-all!", IdKind.EVIDENCE)
    with pytest.raises(InvalidIdError):
        validate_id("evt_2024-01-10", IdKind.EVENT)  # missing slug


def test_slugify_handles_mixed_and_rejects_empty() -> None:
    assert slugify("Mt.Gox 返済 Repayment") == "mt-gox-repayment"
    assert slugify("Fear & Greed", separator="_") == "fear_greed"
    with pytest.raises(InvalidIdError):
        slugify("🚀🚀🚀")
