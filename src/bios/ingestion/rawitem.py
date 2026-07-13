"""RawItem — the unit of collected data (MSD §3.3-1).

Raw payloads are stored verbatim and forever; extraction logic can always
be re-run against history. ``retrieved_at`` is the basis for ``known_at``
downstream: nothing BIOS knows can predate its retrieval.
"""

import hashlib
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from bios.common.errors import BiosError, InvalidIdError
from bios.common.ids import IdKind, new_id, validate_id
from bios.common.schema import BiosModel, BiosRecord
from bios.common.timeutil import ensure_utc, utc_now


def content_hash_of(payload_text: str) -> str:
    """Stable dedup key: sha256 over the exact payload text."""
    return hashlib.sha256(payload_text.encode("utf-8")).hexdigest()


class RawDraft(BiosModel):
    """What an adapter yields: payload plus provenance, before identity."""

    payload_text: str
    content_type: str
    url: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class RawItem(BiosRecord):
    """A stored raw record. Immutable; the raw store refuses overwrites."""

    raw_item_id: str
    source_id: str
    retrieved_at: datetime
    content_hash: str
    content_type: str
    payload_text: str
    url: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("raw_item_id")
    @classmethod
    def _rid(cls, v: str) -> str:
        return _pydantic_id(v, IdKind.RAW_ITEM)

    @field_validator("source_id")
    @classmethod
    def _sid(cls, v: str) -> str:
        return _pydantic_id(v, IdKind.SOURCE)

    @field_validator("retrieved_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        try:
            return ensure_utc(v)
        except BiosError as exc:
            raise ValueError(str(exc)) from exc


def _pydantic_id(value: str, kind: IdKind) -> str:
    try:
        return validate_id(value, kind)
    except InvalidIdError as exc:
        raise ValueError(str(exc)) from exc


def build_raw_item(source_id: str, draft: RawDraft) -> RawItem:
    """Assign identity, retrieval time and dedup hash to an adapter draft."""
    return RawItem(
        raw_item_id=new_id(IdKind.RAW_ITEM),
        source_id=source_id,
        retrieved_at=utc_now(),
        content_hash=content_hash_of(draft.payload_text),
        content_type=draft.content_type,
        payload_text=draft.payload_text,
        url=draft.url,
        meta=draft.meta,
    )
