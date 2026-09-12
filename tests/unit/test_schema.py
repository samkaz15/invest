"""Base model contract tests."""

import pytest
from pydantic import ValidationError

from mios.common import MiosModel, MiosRecord


class Working(MiosModel):
    name: str


class Stored(MiosRecord):
    name: str


def test_unknown_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        Working(name="x", typo_field=1)  # type: ignore[call-arg]


def test_records_are_immutable() -> None:
    record = Stored(name="original")
    with pytest.raises(ValidationError):
        record.name = "mutated"  # type: ignore[misc]


def test_whitespace_stripped() -> None:
    assert Working(name="  padded  ").name == "padded"
