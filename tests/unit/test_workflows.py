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


def test_the_daily_run_covers_the_whole_chain() -> None:
    """Collection through report, in one place.

    A chain missing a step produces a report built on yesterday's numbers
    while looking perfectly healthy.
    """
    used = _workflow_commands(DAILY)
    for command in ("migrate", "collect", "normalize", "forecast", "analyze", "validate", "report"):
        assert command in used, f"daily.yml never runs `{command}`"


def test_the_report_step_is_not_allowed_to_be_skipped_on_error() -> None:
    """A partial failure must still produce the day's snapshot.

    The report names every missing series on its face, so it is most
    valuable exactly on the days something broke.
    """
    document = yaml.safe_load(DAILY.read_text(encoding="utf-8"))
    [job] = document["jobs"].values()
    report_step = next(s for s in job["steps"] if s.get("name") == "Report")
    assert not report_step.get("continue-on-error")


def test_collection_failures_do_not_abort_the_run() -> None:
    """One dead provider is routine; losing the day's snapshot is not."""
    document = yaml.safe_load(DAILY.read_text(encoding="utf-8"))
    [job] = document["jobs"].values()
    resilient = {"Collect", "Normalize", "Forecast", "Analyze", "Validate"}
    for step in job["steps"]:
        if step.get("name") in resilient:
            assert step.get("continue-on-error") is True, (
                f"{step['name']} must not abort the run before the report is written"
            )


def test_the_run_fails_after_committing_not_before() -> None:
    """Failing early would mean the artifact documenting the failure never
    gets written down."""
    document = yaml.safe_load(DAILY.read_text(encoding="utf-8"))
    [job] = document["jobs"].values()
    names = [step.get("name") for step in job["steps"]]
    assert names.index("Commit") < names.index("Fail if any step broke")


def test_the_run_refuses_to_start_without_a_database() -> None:
    """Everything downstream would "succeed" against nothing."""
    text = DAILY.read_text(encoding="utf-8")
    assert "MIOS_DATABASE_URL is not set" in text


def test_ci_runs_the_same_gate_as_make_check() -> None:
    document = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    [job] = document["jobs"].values()
    commands = " ".join(step.get("run", "") for step in job["steps"])
    for tool in ("ruff check", "ruff format --check", "mypy", "pytest"):
        assert tool in commands, f"CI does not run {tool}"
