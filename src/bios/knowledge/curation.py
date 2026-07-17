"""Curation actions: turn an approved queue candidate into a real event.

The human supplies judgment (type, magnitude, title); the machine supplies
provenance (evidence from the candidate's raw item, known_at from
retrieval/publication). This is the teacher-data loop of MSD §3.3-3.
"""

from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

from bios.common.errors import BiosError
from bios.common.ids import IdKind, make_event_id, new_id
from bios.common.labels import EventConfidence, EventStatus, SourceTier
from bios.common.timeutil import TimePrecision, ensure_utc, parse_utc, utc_now
from bios.knowledge.models import EventRecord, EvidenceRecord
from bios.knowledge.store import CurationQueue, EventStore, IntegrityError


def _published_at(payload: dict[str, Any]) -> datetime | None:
    raw = payload.get("published_raw")
    if not raw:
        return None
    try:
        return ensure_utc(parsedate_to_datetime(str(raw)))  # RFC 822 (RSS)
    except (TypeError, ValueError, BiosError):
        try:
            return parse_utc(str(raw))  # ISO 8601 (Atom)
        except BiosError:
            return None


def approve_candidate(
    store: EventStore,
    queue: CurationQueue,
    candidate: dict[str, Any],
    event_type: str,
    magnitude: int,
    title: str | None = None,
    summary_fact: str | None = None,
    slug: str | None = None,
    asset_id: str = "ent_asset_btc",
) -> EventRecord:
    """Approve one candidate: build event + evidence, store, resolve queue."""
    payload: dict[str, Any] = candidate["payload"]
    published = _published_at(payload)
    retrieved = parse_utc(payload["retrieved_at"])
    occurred_at = published or retrieved
    known_at = max(occurred_at, published or occurred_at)
    resolved_title = title or str(payload.get("title") or "")
    if not resolved_title:
        raise IntegrityError(f"candidate {candidate['candidate_id']}: no title")

    event = EventRecord(
        event_id=make_event_id(occurred_at.date().isoformat(), slug or resolved_title),
        type=event_type,
        title=resolved_title,
        summary_fact=summary_fact or resolved_title,
        occurred_at=occurred_at,
        known_at=known_at,
        time_precision=TimePrecision.MINUTE if published else TimePrecision.DAY,
        confidence=(
            EventConfidence.VERIFIED
            if int(payload.get("tier", 4)) == 1
            else EventConfidence.REPORTED
        ),
        status=EventStatus.CONFIRMED,
        magnitude_initial=magnitude,
        assets=[{"asset_id": asset_id, "relevance": 1.0}],
        curation={
            "by": "human",
            "reviewed_at": utc_now().isoformat(),
            "candidate_id": candidate["candidate_id"],
        },
    )
    evidence = EvidenceRecord(
        evidence_id=new_id(IdKind.EVIDENCE),
        source_id=str(payload["source_id"]),
        tier=SourceTier(int(payload.get("tier", 4))),
        url=payload.get("link"),
        quote=str(payload.get("summary") or "")[:1000],
        published_at=published,
        retrieved_at=retrieved,
        raw_item_id=payload.get("raw_item_id"),
    )
    store.insert_event(event, [evidence])
    queue.resolve(candidate["candidate_id"], "approved", event_id=event.event_id)
    return event
