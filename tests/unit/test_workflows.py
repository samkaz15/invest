"""The workflows must stay in step with the CLI.

A renamed command is a silent breakage: the workflow keeps running on its
schedule and fails every night at 07:10 UTC, which is the worst possible
place to discover it. These tests read the YAML and check it against the
actual argument parser.
"""

import re
from pathlib import Path

import yaml

from mios.cli import main

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
DAILY = WORKFLOWS / "daily.yml"


def _known_commands() -> set[str]:
    """Every subcommand the CLI actually accepts."""
    import argparse
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.suppress(SystemExit), contextlib.redirect_stdout(buffer):
        main(["--help"])
    text = buffer.getvalue()
    # argparse lists subcommands in a {a,b,c} block.
    match = re.search(r"\{([a-z,\-]+)\}", text)
    assert match, f"could not read subcommands from --help:\n{text}"
    assert argparse  # imported for the intent, not used directly
    return set(match.group(1).split(","))


def _workflow_commands(path: Path) -> set[str]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for job in document["jobs"].values():
        for step in job["steps"]:
            run = step.get("run", "")
            for match in re.finditer(r"python -m mios\.cli ([a-z\-]+)", run):
                found.add(match.group(1))
    return found


def test_every_workflow_command_exists_in_the_cli() -> None:
    unknown = _workflow_commands(DAILY) - _known_commands()
    assert not unknown, f"daily.yml calls commands the CLI does not have: {sorted(unknown)}"


def test_the_workflow_and_the_makefile_run_the_same_chain() -> None:
    """The drift this guards against actually happened.

    The chain was written out step by step in the workflow and again in the
    Makefile. The workflow tolerated a failing collection and still wrote the
    report; `make daily-report` stopped at the first error and produced
    nothing — so the documented behaviour was true in one place and false in
    the other. Both now call one command.
    """
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    assert "mios.cli daily" in makefile
    assert _workflow_commands(DAILY) == {"daily"}


def test_the_chain_covers_every_step_from_collection_to_report() -> None:
    """A chain missing a step produces a report built on yesterday's numbers
    while looking perfectly healthy."""
    from mios.cli import DAILY_CHAIN

    steps = [step for step, _ in DAILY_CHAIN]
    assert steps == [
        "migrate",
        "collect",
        "normalize",
        # After normalize: the calendar reads its own collected payload, and
        # releases read the observations normalize just wrote.
        "calendar",
        "releases",
        "forecast",
        "analyze",
        "validate",
        "report",
        # After report: the CSVs render what is already stored, so a failure
        # here loses a convenience rather than a record.
        "export",
    ]


def test_collection_may_fail_but_the_report_may_not_be_skipped() -> None:
    """One dead provider is routine; losing the day's snapshot is not.

    The report names every missing series on its face, so it is most
    valuable exactly on the days something broke.
    """
    from mios.cli import DAILY_CHAIN

    tolerant = {step: ok for step, ok in DAILY_CHAIN}
    for step in (
        "collect",
        "normalize",
        "calendar",
        "releases",
        "forecast",
        "analyze",
        "validate",
    ):
        assert tolerant[step] is True, f"{step} must not abort the run before the report"
    assert tolerant["report"] is False
    assert tolerant["migrate"] is False


def test_the_run_fails_after_committing_not_before() -> None:
    """Failing early would mean the artifact documenting the failure never
    gets written down."""
    document = yaml.safe_load(DAILY.read_text(encoding="utf-8"))
    [job] = document["jobs"].values()
    names = [step.get("name") for step in job["steps"]]
    assert names.index("Commit") < names.index("Fail if the chain reported an error")
    chain_step = next(s for s in job["steps"] if s.get("name") == "Daily chain")
    assert chain_step.get("continue-on-error") is True


def test_the_run_refuses_to_start_without_a_database() -> None:
    """Everything downstream would "succeed" against nothing."""
    text = DAILY.read_text(encoding="utf-8")
    assert "MIOS_DATABASE_URL is not set" in text


def test_the_verify_workflow_touches_no_database() -> None:
    """A check that writes is not a check.

    `verify-sources` fetches and parses and stores nothing, which is what
    makes it safe to run against production credentials at any time. Handing
    it a database URL would invite that to change quietly.
    """
    document = yaml.safe_load((WORKFLOWS / "verify-sources.yml").read_text(encoding="utf-8"))
    [job] = document["jobs"].values()
    assert "MIOS_DATABASE_URL" not in job.get("env", {})


def test_the_verify_workflow_calls_the_verify_command() -> None:
    used = _workflow_commands(WORKFLOWS / "verify-sources.yml")
    assert used == {"verify-sources"}
    assert "verify-sources" in _known_commands()


def test_ci_runs_the_same_gate_as_make_check() -> None:
    document = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    [job] = document["jobs"].values()
    commands = " ".join(step.get("run", "") for step in job["steps"])
    for tool in ("ruff check", "ruff format --check", "mypy", "pytest"):
        assert tool in commands, f"CI does not run {tool}"
