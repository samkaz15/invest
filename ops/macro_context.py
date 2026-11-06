#!/usr/bin/env python3
"""Create a point-in-time, non-predictive index of saved US official knowledge.

No web access, no LLM, no alteration of the existing numerical forecasts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VERSION = "macro-context/v1"


def timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return result.astimezone(UTC)


def build_context(directory: Path, as_of: datetime) -> dict[str, Any]:
    if as_of.utcoffset() is None:
        raise ValueError("as_of must include timezone")
    if not directory.is_dir():
        raise FileNotFoundError(f"knowledge directory does not exist: {directory}")
    records: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            content = path.read_bytes()
            item = json.loads(content)
            if not isinstance(item, dict):
                raise ValueError("record is not an object")
            published = timestamp(item.get("published_at"))
            received = timestamp(item.get("received_at"))
            if published > as_of or received > as_of:
                rejected.append({"path": str(path), "reason": "not available at as_of"})
                continue
            url, ident, original = item.get("source_url"), item.get("id"), item.get("original_text")
            if not all(isinstance(v, str) and v.strip() for v in (url, ident, original)):
                raise ValueError("missing source_url, id or original_text")
            if not url.startswith("https://"):
                raise ValueError("source_url must use https")
            facts = item.get("facts_ja")
            topics = item.get("topics")
            if not isinstance(facts, list) or not all(isinstance(v, str) for v in facts):
                raise ValueError("invalid facts_ja")
            if not isinstance(topics, list) or not all(isinstance(v, str) for v in topics):
                raise ValueError("invalid topics")
            raw_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()
            record = {
                "id": ident,
                "source_url": url,
                "published_at": published.isoformat(),
                "received_at": received.isoformat(),
                "topics": topics,
                "facts_ja": facts,
                "record_path": str(path),
                "record_sha256": hashlib.sha256(content).hexdigest(),
                "original_sha256": raw_hash,
                "label": "REPORTED_SOURCE_CONTENT",
            }
            candidates.append((url, published.isoformat() + raw_hash, record))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            rejected.append({"path": str(path), "reason": f"invalid or incomplete: {exc}"})
    seen: set[tuple[str, str]] = set()
    for url, fingerprint, record in candidates:
        key = (url, fingerprint)
        if key in seen:
            rejected.append({"path": record["record_path"], "reason": "duplicate document"})
            continue
        seen.add(key)
        records.append(record)
    return {
        "schema_version": VERSION,
        "as_of": as_of.astimezone(UTC).isoformat(),
        "purpose": "source index only; no new forecasts or trading signals",
        "historical_replay_warning": (
            "Timestamps alone do not prove the saved record existed unchanged at as_of; "
            "use an archived repository snapshot from that time."
        ),
        "documents": records,
        "excluded": rejected,
        "missing": [
            "consensus",
            "CPI and employment new forecast",
            "intraday prices",
            "gold demand and positioning",
            "USD/JPY and XAU/USD forecast",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="Timezone-aware ISO 8601 timestamp")
    parser.add_argument("--knowledge-dir", type=Path, default=Path("data/knowledge/us"))
    parser.add_argument(
        "--output", type=Path, required=True, help="New JSON path; never overwrites"
    )
    args = parser.parse_args()
    try:
        report = build_context(args.knowledge_dir, timestamp(args.as_of))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(
        f"Wrote {args.output}; documents={len(report['documents'])}, "
        f"excluded={len(report['excluded'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
