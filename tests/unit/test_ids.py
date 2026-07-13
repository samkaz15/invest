"""ID convention tests (bios.common.ids)."""

import pytest

from bios.common import IdKind, InvalidIdError, make_event_id, new_id, validate_id
from bios.common.ids import slugify


def test_new_id_carries_prefix_and_validates() -> None:
    for kind in IdKind:
        if kind is IdKind.EVENT:
            continue  # events use make_event_id
        value = new_id(kind)
        assert validate_id(value, kind) == value


def test_new_ids_are_unique_and_sortable() -> None:
    ids = [new_id(IdKind.RAW_ITEM) for _ in range(200)]
    assert len(set(ids)) == 200
    # time-prefixed: batch generated now sorts after a fabricated older id
    old = "raw_00000000000abcdef"
    assert all(old < i for i in ids)


def test_make_event_id_human_readable() -> None:
    assert make_event_id("2024-01-10", "ETF Approval!") == "evt_2024-01-10_etf-approval"
    assert validate_id("evt_2024-01-10_etf-approval", IdKind.EVENT)


def test_make_event_id_rejects_bad_date() -> None:
    with pytest.raises(InvalidIdError):
        make_event_id("10/01/2024", "etf")


def test_validate_id_rejects_wrong_prefix_and_shape() -> None:
    with pytest.raises(InvalidIdError):
        validate_id("evd_deadbeefdeadbeef1", IdKind.EVENT)
    with pytest.raises(InvalidIdError):
        validate_id("evt_2024-01-10_etf approval", IdKind.EVENT)
    with pytest.raises(InvalidIdError):
        validate_id("raw_notHEX", IdKind.RAW_ITEM)


def test_slugify_rejects_unusable_text() -> None:
    assert slugify("Mt.Gox 返済 Repayment") == "mt-gox-repayment"
    with pytest.raises(InvalidIdError):
        slugify("🚀🚀🚀")
