"""Replay public US knowledge records into PostgreSQL; never overwrite history."""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from mios.storage.db import Database
from mios.storage.migrate import MigrationRunner

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "id", "source_url", "title_en", "title_ja", "published_at", "received_at",
    "topics", "original_text", "translation_ja", "facts_ja", "inference_ja",
}


def load_record(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    missing = REQUIRED - doc.keys()
    if missing:
        raise ValueError(f"{path}: missing {sorted(missing)}")
    if not isinstance(doc["id"], str) or not doc["id"]:
        raise ValueError(f"{path}: invalid id")
    if not isinstance(doc["topics"], list) or not doc["topics"]:
        raise ValueError(f"{path}: topics required")
    if not all(isinstance(t, str) for t in doc["topics"]):
        raise ValueError(f"{path}: invalid topics")
    for key in ("source_url", "title_en", "title_ja", "original_text", "translation_ja"):
        if not isinstance(doc[key], str) or not doc[key].strip():
            raise ValueError(f"{path}: invalid {key}")
    if not doc["source_url"].startswith("https://"):
        raise ValueError(f"{path}: HTTPS source required")
    for key in ("received_at", "published_at"):
        value = doc[key]
        if key == "published_at" and value is None:
            continue
        if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError(f"{path}: {key} requires timezone")
    canonical = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return doc, canonical, hashlib.sha256(canonical.encode()).hexdigest()


def main():
    records = [load_record(p) for p in sorted((ROOT / "data/knowledge/us").glob("*.json"))]
    db = Database(os.environ["MIOS_DATABASE_URL"])
    MigrationRunner(db, ROOT / "db/migrations").apply_all()
    with db.transaction() as conn:
        for doc, canonical, digest in records:
            conn.execute(
                """INSERT INTO us_knowledge_documents
                (id, source_url, published_at, received_at, topics, document, content_sha256)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (id) DO NOTHING""",
                (doc["id"], doc["source_url"], doc["published_at"], doc["received_at"],
                 json.dumps(doc["topics"]), canonical, digest),
            )
            row = conn.execute(
                "SELECT content_sha256 FROM us_knowledge_documents WHERE id = %s",
                (doc["id"],),
            ).fetchone()
            if row["content_sha256"] != digest:
                raise ValueError(f"immutable record conflict: {doc['id']}")
    print(f"US knowledge records synchronized: {len(records)}")


if __name__ == "__main__":
    main()
