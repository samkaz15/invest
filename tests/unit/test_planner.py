"""Which observations get written, and why.

The invariant under test: **a row exists for every moment the published
value changed, and for no other moment.** It has to hold whether data
arrives from a daily poll, from a backfill carrying a decade of revisions
at once, or from a second backfill overlapping the first — and the result
must be identical in all three cases, because a backtest run against
backfilled history has to match one run against history collected live.
"""

from datetime import UTC, datetime
from decimal import Decimal

from mios.series.planner import plan_writes, same_value


def _at(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=UTC)


def _d(text: str) -> Decimal:
    return Decimal(text)


SEP = _at("2026-09-11")
OCT = _at("2026-10-13")
NOV = _at("2026-11-13")


def test_first_figure_for_a_period_is_written_and_is_not_a_revision() -> None:
    [planned] = plan_writes([], [(SEP, _d("325.4"))])
    assert planned.value == _d("325.4")
    assert planned.revision_n == 0
    assert planned.is_revision is False


def test_an_unchanged_repeat_is_not_written() -> None:
    assert plan_writes([(SEP, _d("325.4"))], [(OCT, _d("325.4"))]) == []


def test_a_changed_value_is_written_as_a_revision() -> None:
    [planned] = plan_writes([(SEP, _d("325.4"))], [(OCT, _d("325.6"))])
    assert (planned.value, planned.revision_n, planned.is_revision) == (_d("325.6"), 1, True)


def test_an_exact_duplicate_vintage_is_dropped() -> None:
    """Re-running a backfill must be a no-op, not a conflict."""
    assert plan_writes([(SEP, _d("325.4"))], [(SEP, _d("325.4"))]) == []
    assert plan_writes([(SEP, _d("325.4"))], [(SEP, _d("999.9"))]) == []


def test_a_backfill_of_ordered_history_records_every_change() -> None:
    planned = plan_writes([], [(SEP, _d("325.4")), (OCT, _d("325.6")), (NOV, _d("325.6"))])
    # The November pull restated nothing, so it leaves no trace.
    assert [(p.vintage_at, p.value, p.revision_n) for p in planned] == [
        (SEP, _d("325.4"), 0),
        (OCT, _d("325.6"), 1),
    ]


def test_a_backfill_arriving_newest_first_gives_the_same_answer() -> None:
    """Providers order responses however they like; the result must not."""
    forwards = plan_writes([], [(SEP, _d("325.4")), (OCT, _d("325.6"))])
    backwards = plan_writes([], [(OCT, _d("325.6")), (SEP, _d("325.4"))])
    assert [(p.vintage_at, p.value, p.revision_n) for p in forwards] == [
        (p.vintage_at, p.value, p.revision_n) for p in backwards
    ]


def test_a_vintage_inserted_between_two_stored_ones_is_judged_by_what_preceded_it() -> None:
    """The case that makes naive "compare to latest" logic wrong.

    A later ALFRED backfill can reveal an intermediate vintage that was
    missed while polling. It must be judged against the value in force just
    before it — not against the newest row in the table, which belongs to a
    later moment entirely.
    """
    existing = [(SEP, _d("325.4")), (NOV, _d("325.9"))]
    [planned] = plan_writes(existing, [(OCT, _d("325.6"))])
    assert planned.value == _d("325.6")
    assert planned.revision_n == 1  # one change preceded it
    assert planned.is_revision is True


def test_an_intermediate_vintage_equal_to_its_predecessor_is_not_written() -> None:
    existing = [(SEP, _d("325.4")), (NOV, _d("325.9"))]
    assert plan_writes(existing, [(OCT, _d("325.4"))]) == []


def test_a_published_gap_is_a_value_not_an_absence() -> None:
    """`None` means "the agency reported no figure", which is information.

    So a gap followed by a real number is a revision, and a gap repeated is
    not — exactly as for any other value.
    """
    [first] = plan_writes([], [(SEP, None)])
    assert first.value is None and first.is_revision is False

    assert plan_writes([(SEP, None)], [(OCT, None)]) == []

    [filled] = plan_writes([(SEP, None)], [(OCT, _d("325.4"))])
    assert filled.value == _d("325.4") and filled.is_revision is True


def test_reformatted_equal_values_are_not_revisions() -> None:
    assert same_value(_d("325.40"), _d("325.4"))
    assert plan_writes([(SEP, _d("325.40"))], [(OCT, _d("325.4"))]) == []


def test_a_batch_is_judged_against_its_own_accepted_points() -> None:
    """Within one payload, later points see the earlier ones.

    Otherwise a three-vintage backfill of 1 -> 2 -> 2 would write the final
    unchanged repeat, because each point would be compared only against
    what was in the database before the batch began.
    """
    planned = plan_writes([], [(SEP, _d("1")), (OCT, _d("2")), (NOV, _d("2"))])
    assert [p.value for p in planned] == [_d("1"), _d("2")]


def test_replaying_a_backfill_over_its_own_result_changes_nothing() -> None:
    """Idempotence, stated directly.

    Weekly ALFRED pulls overlap almost entirely; if this did not hold, the
    table would grow without bound and revision counts would be fiction.
    """
    history = [(SEP, _d("325.4")), (OCT, _d("325.6")), (NOV, _d("325.9"))]
    first_pass = plan_writes([], history)
    stored = [(p.vintage_at, p.value) for p in first_pass]
    assert plan_writes(stored, history) == []
