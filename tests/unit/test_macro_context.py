"""Point-in-time guardrails for the existing US knowledge archive."""

import json
from pathlib import Path

import pytest
from ops.macro_context import build_context, timestamp

AS_OF = timestamp("2026-11-06T10:00:00Z")


def write_record(directory: Path, name: str, **changes: object) -> None:
    item: dict[str, object] = {
        "id": name,
        "source_url": "https://example.gov/doc",
        "original_text": "source",
        "published_at": "2026-11-05T10:00:00Z",
        "received_at": "2026-11-05T11:00:00Z",
        "facts_ja": ["内容"],
        "topics": ["oil"],
    }
    item.update(changes)
    (directory / f"{name}.json").write_text(json.dumps(item), encoding="utf-8")


def test_excludes_future_publication_and_retrieval_and_unknown_time(tmp_path: Path) -> None:
    write_record(tmp_path, "valid")
    write_record(tmp_path, "future", published_at="2026-11-07T00:00:00Z")
    write_record(tmp_path, "late", received_at="2026-11-07T00:00:00Z")
    write_record(tmp_path, "unknown", published_at=None)
    result = build_context(tmp_path, AS_OF)
    assert [r["id"] for r in result["documents"]] == ["valid"]
    assert len(result["excluded"]) == 3


def test_dedup_and_distinct_correction(tmp_path: Path) -> None:
    write_record(tmp_path, "a")
    write_record(tmp_path, "b")
    write_record(tmp_path, "c", original_text="corrected source")
    result = build_context(tmp_path, AS_OF)
    assert [r["id"] for r in result["documents"]] == ["a", "c"]
    assert result["excluded"][0]["reason"] == "duplicate document"


def test_invalid_inputs_do_not_become_facts(tmp_path: Path) -> None:
    write_record(tmp_path, "a", facts_ja="not a list")
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    result = build_context(tmp_path, AS_OF)
    assert result["documents"] == []
    assert len(result["excluded"]) == 2
    with pytest.raises(ValueError):
        timestamp("2026-11-06T10:00:00")
    with pytest.raises(FileNotFoundError):
        build_context(tmp_path / "missing", AS_OF)
