"""Static guards against look-ahead bias.

The as-of discipline is the one rule that cannot be enforced by review
alone: it fails silently, the tests still pass, and the damage only shows
up months later as a backtest that was always going to look good. So it is
checked the same way the layer boundaries are — by reading the source.

Three things are guaranteed here:

1. Nothing outside a named owner module reaches `observations` or
   `predictions` with raw SQL.
2. Every as-of read takes an explicit instant; none default to "now".
3. A revisable series has no accessor that returns "the current value".

See CONSTITUTION.md Art.6 and docs/REPOSITORY_AUDIT.md §14.
"""

import ast
import inspect
from pathlib import Path

from mios.series.repo import ObservationRepo

SRC = Path(__file__).resolve().parents[2] / "src" / "mios"
REPO_MODULE = SRC / "series" / "repo.py"

#: Modules allowed to write SQL against the time-ordered tables. Each one
#: takes on the as-of discipline by hand, so the list should stay short:
#: every name here is a place the guarantee has to be re-checked in review.
SQL_OWNERS = {
    REPO_MODULE,
    SRC / "prediction" / "repo.py",
    SRC / "prediction" / "external.py",
    SRC / "validation" / "scoring.py",
    SRC / "validation" / "metrics.py",
    SRC / "validation" / "benchmark.py",
}

#: Tables where reading without a cutoff is a look-ahead bug rather than a
#: style problem. The two `*_forecast_errors` tables are deliberately
#: absent: they are present-time views of accumulated evidence, not
#: historical replays.
#:
#: `external_forecasts` is here for a reason worth stating. Backfilling an
#: outside forecaster's history gives rows whose published_at is old and
#: whose vintage_at is the day MIOS fetched them. A read that forgets the
#: cutoff would credit MIOS with having known a year of nowcasts it had not
#: yet downloaded, and the resulting comparison would look excellent.
VINTAGE_TABLES = (
    "observations",
    "normalize_state",
    "predictions",
    "external_forecasts",
)


def _python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_only_the_repository_queries_the_vintage_tables() -> None:
    """Raw SQL elsewhere would bypass the as-of filter entirely.

    A `SELECT * FROM observations` in an analysis module is not a style
    problem — it is a silent look-ahead bug, because nothing in the query
    mentions a cutoff and nothing in review reliably catches its absence.
    """
    offenders: list[str] = []
    for path in _python_files():
        if path in SQL_OWNERS:
            continue
        for literal in _string_literals(path):
            lowered = literal.lower()
            # Require a statement keyword so prose mentioning a table name
            # in a docstring is not mistaken for a query.
            if not any(verb in lowered for verb in ("select ", "insert ", "update ", "delete ")):
                continue
            for table in VINTAGE_TABLES:
                if f"from {table}" in lowered or f"into {table}" in lowered:
                    offenders.append(f"{path.relative_to(SRC)}: SQL against {table!r}")
    assert not offenders, (
        "read vintage data through ObservationRepo, which requires an as-of:\n"
        + "\n".join(offenders)
    )


def test_as_of_parameters_have_no_default() -> None:
    """A default would be an invitation to read the present by accident.

    `as_of(series)` returning today's view is the kind of call that looks
    correct at every call site and is wrong at half of them. Making the
    argument required forces the caller to decide, every time, which moment
    they mean.
    """
    tree = ast.parse(REPO_MODULE.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        args = node.args
        # defaults align to the tail of args
        defaulted = dict(
            zip(
                [a.arg for a in args.args][-len(args.defaults) :] if args.defaults else [],
                args.defaults,
                strict=False,
            )
        )
        defaulted.update(
            {
                a.arg: d
                for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=False)
                if d is not None
            }
        )
        if "as_of" in defaulted:
            offenders.append(f"{node.name}() gives as_of a default")
    assert not offenders, "\n".join(offenders)


def test_every_observation_read_requires_an_as_of() -> None:
    """No accessor may hand back "the value now" for a revisable series."""
    readers = ("as_of", "latest_as_of")
    for name in readers:
        signature = inspect.signature(getattr(ObservationRepo, name))
        parameter = signature.parameters["as_of"]
        assert parameter.default is inspect.Parameter.empty, (
            f"ObservationRepo.{name} must require an explicit as_of"
        )


def test_the_repository_never_reaches_for_the_wall_clock() -> None:
    """`utc_now()` inside a read path is how "as of now" creeps back in.

    Writes legitimately record ingest time — that is the database's
    `now()` default, not this module's business — so the module simply does
    not import a clock at all.
    """
    source = REPO_MODULE.read_text(encoding="utf-8")
    assert "utc_now" not in source, (
        "series/repo.py must not consult the clock: a read that can invent "
        "its own cutoff is a read that can see the future"
    )
