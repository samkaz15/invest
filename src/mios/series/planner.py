"""Deciding which observations to actually write.

Pulled out of the repository because it is the one piece of vintage logic
with real edge cases, and it is worth being able to test it without a
database.

The rule: **a row exists for every moment the published value changed, and
for no other moment.** That has to hold whether points arrive newest-first
from a daily poll, or as a backfill carrying a decade of revisions in one
payload, or as a second backfill overlapping the first.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

Vintage = tuple[datetime, Decimal | None]


@dataclass(frozen=True)
class PlannedWrite:
    vintage_at: datetime
    value: Decimal | None
    revision_n: int
    #: True when this supersedes a value we already had, rather than being
    #: the first figure for the period. Counted separately so "how often was
    #: this restated?" stays answerable.
    is_revision: bool


def same_value(left: Decimal | None, right: Decimal | None) -> bool:
    """Compare two readings, treating a published gap as a real value.

    Decimal comparison is numeric, so a provider reformatting 3.20 as 3.2
    does not masquerade as a revision.
    """
    if left is None or right is None:
        return left is None and right is None
    return left == right


def plan_writes(existing: list[Vintage], incoming: list[Vintage]) -> list[PlannedWrite]:
    """Which of ``incoming`` are genuinely new information.

    ``existing`` is every vintage already stored for one reference period.
    A candidate is written when the value in force immediately *before* its
    vintage differs from it — which is what makes this correct for
    backfills as well as for polling. A point inserted between two stored
    vintages is judged against the one that preceded it in time, not
    against the newest row in the table, so importing history out of order
    produces the same result as having collected it live.

    Exact duplicates of a stored vintage are dropped: re-running a backfill
    must be a no-op.
    """
    stored = {vintage: value for vintage, value in existing}
    timeline: list[Vintage] = sorted(existing, key=lambda v: v[0])

    candidates = sorted(
        (v for v in incoming if v[0] not in stored),
        key=lambda v: v[0],
    )

    planned: list[PlannedWrite] = []
    for vintage_at, value in candidates:
        had_predecessor, preceding = _value_before(timeline, vintage_at)
        if had_predecessor and same_value(preceding, value):
            continue
        planned.append(
            PlannedWrite(
                vintage_at=vintage_at,
                value=value,
                revision_n=_changes_before(timeline, vintage_at),
                is_revision=had_predecessor,
            )
        )
        # Accepted points join the timeline so a later candidate in the same
        # batch is judged against them, not against a stale picture.
        timeline.append((vintage_at, value))
        timeline.sort(key=lambda v: v[0])
    return planned


def _value_before(timeline: list[Vintage], moment: datetime) -> tuple[bool, Decimal | None]:
    """The value in force just before ``moment``, and whether there was one.

    The boolean is load-bearing: a stored ``None`` means "the publisher
    reported no figure", which is a statement about the data, while "no
    vintage precedes this one" means there was nothing to state. Returning
    a bare ``None`` would conflate the two and make the first figure of a
    period look like an unchanged repeat of a gap.
    """
    found = False
    latest: Decimal | None = None
    for vintage_at, value in timeline:
        if vintage_at < moment:
            found, latest = True, value
        else:
            break
    return found, latest


def _changes_before(timeline: list[Vintage], moment: datetime) -> int:
    """How many times the value had already changed before ``moment``.

    Every stored vintage is a change by construction (that is the invariant
    this module maintains), so this is simply how many precede it.
    """
    return sum(1 for vintage_at, _ in timeline if vintage_at < moment)
