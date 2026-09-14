"""Consensus forecasts a human transcribed, stored like any other forecast.

ADR-012 established that MIOS has no free, machine-readable consensus for
NFP or the unemployment rate: the monthly economist surveys are a commercial
product. That is still true, and this does not change it by scraping one.
Broker calendars show those numbers because a person is meant to read them;
collecting them automatically and committing them to a public repository
would be redistributing someone else's licensed dataset.

Reading a page with your own eyes and writing a number down is not that. So
this is the path: `input/consensus.csv` is typed by hand and ingested here,
into exactly the same table, under exactly the same rules as the Cleveland
Fed nowcast — append-only, vintage-stamped, source URL required. A consensus
written down ten days before a release survives being revised the day
before, which is the whole point.

**The unit conversion is the dangerous part**, and it is why this module
exists rather than a column in the CSV being multiplied somewhere. Three
things a calendar shows look alike and are not:

    "+0.3%"      a month-over-month change        → 0.003
    "+175k"      a change in a level, in thousands → 175
    "4.3%"       a *level*, not a change           → 4.3 minus last month's

The third is the one that silently ruins a comparison. The unemployment rate
is quoted as a level and forecast by MIOS as a change, so storing 4.3
unconverted would record a consensus of "+4.3 percentage points" — a number
that is not wrong by a rounding error but by two orders of magnitude, and
which would make every human forecaster look catastrophically bad.
"""

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from mios.common.errors import MiosError
from mios.common.ids import IdKind, make_dated_id, slugify
from mios.common.logutil import get_logger
from mios.common.timeutil import parse_utc
from mios.config.forecast import TargetSpec
from mios.prediction.external import ExternalForecastRepo
from mios.series.repo import ObservationRepo

logger = get_logger(__name__)

PROVIDER_ID = "src_manual_consensus"

#: What the number written in the file means.
UNITS = {
    #: A period-over-period percent, as a calendar prints it ("+0.3%").
    "percent_change": "percent_change",
    #: A change in the series' own level, in the series' own units ("+175k"
    #: where payrolls are counted in thousands).
    "level_change": "level_change",
    #: A level ("4.3%"). Converted to a change against the previous period
    #: as it stood when the forecast was read.
    "level": "level",
}

COLUMNS = [
    "target_series_id",
    "target_period",
    "value",
    "unit",
    "observed_at",
    "source_url",
    "note",
]


class ConsensusInputError(MiosError):
    """A row in the input file could not be trusted, so none of it is used."""


@dataclass
class ManualReport:
    rows: int = 0
    written: int = 0
    unchanged: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class ConsensusRow:
    target_series_id: str
    target_period: date
    value: Decimal
    unit: str
    observed_at: datetime
    source_url: str
    note: str


def read_rows(path: Path) -> list[ConsensusRow]:
    """Parse the hand-typed file, refusing anything ambiguous.

    Every failure here raises rather than skipping the row. A consensus file
    that silently drops the line you just typed is worse than one that will
    not load: you would go on believing the number was recorded, and find out
    six months later when the comparison had a hole in it.
    """
    if not path.is_file():
        return []
    lines = [
        line
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        return []

    reader = csv.DictReader(lines)
    if reader.fieldnames is None or [f.strip() for f in reader.fieldnames] != COLUMNS:
        raise ConsensusInputError(
            f"{path}: header must be exactly {','.join(COLUMNS)}; found {reader.fieldnames}"
        )

    out: list[ConsensusRow] = []
    for number, raw in enumerate(reader, start=2):
        where = f"{path} row {number}"
        unit = (raw.get("unit") or "").strip()
        if unit not in UNITS:
            raise ConsensusInputError(
                f"{where}: unit must be one of {sorted(UNITS)}; found {unit!r}"
            )
        url = (raw.get("source_url") or "").strip()
        if not url.startswith("http"):
            # 指示書 §26: no figure without provenance. A consensus nobody
            # can trace is a number somebody remembered.
            raise ConsensusInputError(f"{where}: source_url is required and must be a URL")
        try:
            value = Decimal((raw.get("value") or "").strip())
            period = date.fromisoformat((raw.get("target_period") or "").strip())
            observed = parse_utc((raw.get("observed_at") or "").strip())
        except (InvalidOperation, ValueError, MiosError) as exc:
            raise ConsensusInputError(f"{where}: {exc}") from exc

        out.append(
            ConsensusRow(
                target_series_id=(raw.get("target_series_id") or "").strip(),
                target_period=period,
                value=value,
                unit=unit,
                observed_at=observed,
                source_url=url,
                note=(raw.get("note") or "").strip(),
            )
        )
    return out


def convert(
    row: ConsensusRow,
    spec: TargetSpec,
    observations: ObservationRepo,
) -> Decimal:
    """Turn what the calendar printed into what MIOS forecasts.

    Raises rather than guessing when the unit and the target disagree: a
    percent handed to a target forecast as a level difference is the error
    that produces a plausible-looking wrong answer.
    """
    if spec.transform == "pct_change":
        if row.unit != "percent_change":
            raise ConsensusInputError(
                f"{row.target_series_id} is forecast as a percent change, so unit must be "
                f"'percent_change'; found {row.unit!r}"
            )
        return row.value / Decimal(100)

    if row.unit == "level_change":
        return row.value
    if row.unit == "percent_change":
        raise ConsensusInputError(
            f"{row.target_series_id} is forecast as a level difference, so a percent "
            "cannot be converted without assuming a base"
        )

    # unit == "level": a quoted level becomes a change against the previous
    # period *as it stood when the forecast was read* — not against today's
    # restated value, which the forecaster could not have seen.
    previous = _previous_level(observations, row, spec)
    if previous is None:
        raise ConsensusInputError(
            f"{row.target_series_id} {row.target_period}: a level consensus needs the "
            "previous period's value, and none was knowable at "
            f"{row.observed_at.isoformat()} — collect the series first"
        )
    return row.value - previous


def _previous_level(
    observations: ObservationRepo, row: ConsensusRow, spec: TargetSpec
) -> Decimal | None:
    period = row.target_period
    prior = (
        date(period.year - 1, 12, 1)
        if period.month == 1
        else date(period.year, period.month - 1, 1)
    )
    rows = observations.as_of(spec.series_id, row.observed_at, end=prior)
    usable = [r for r in rows if r.value is not None]
    return usable[-1].value if usable else None


class ManualConsensusIngestor:
    def __init__(
        self,
        path: Path,
        repo: ExternalForecastRepo,
        observations: ObservationRepo,
        targets: dict[str, TargetSpec],
        source_url: str,
        tier: int,
    ) -> None:
        self._path = path
        self._repo = repo
        self._observations = observations
        self._targets = targets
        self._source_url = source_url
        self._tier = tier

    def run(self) -> ManualReport:
        report = ManualReport()
        try:
            rows = read_rows(self._path)
        except ConsensusInputError as exc:
            report.failures.append(str(exc))
            logger.error("consensus input: %s", exc)
            return report

        report.rows = len(rows)
        for row in rows:
            spec = self._targets.get(row.target_series_id)
            if spec is None:
                report.failures.append(
                    f"{row.target_series_id} is not a forecast target — there would be "
                    "nothing to compare it against"
                )
                continue
            try:
                value = convert(row, spec, self._observations)
            except ConsensusInputError as exc:
                report.failures.append(str(exc))
                continue

            previous = self._repo.latest(PROVIDER_ID, row.target_series_id, row.target_period)
            if previous is not None and Decimal(str(previous["point_value"])) == value:
                # Re-typing the same number is not a new opinion.
                report.unchanged += 1
                continue

            slug = slugify(
                f"manual-{row.target_series_id.removeprefix('ser_')}-"
                f"{row.target_period.isoformat()}"
            )
            written = self._repo.save(
                {
                    "external_forecast_id": make_dated_id(
                        IdKind.EXTERNAL_FORECAST, row.observed_at.date().isoformat(), slug
                    ),
                    "provider_id": PROVIDER_ID,
                    "target_series_id": row.target_series_id,
                    "target_period": row.target_period,
                    "published_at": row.observed_at,
                    # Both are the moment it was read. A transcribed figure
                    # became knowable to MIOS when someone typed it, and
                    # claiming otherwise would let a backfilled sheet look
                    # like a forecast held all along.
                    "vintage_at": row.observed_at,
                    "point_value": value,
                    "raw_value": row.value,
                    "raw_unit": row.unit,
                    "tier": self._tier,
                    "method": row.note or "手入力のコンセンサス予想",
                    "source_url": row.source_url,
                    "raw_item_id": None,
                }
            )
            if written:
                report.written += 1
            else:
                report.unchanged += 1

        logger.info(
            "manual consensus: rows=%d written=%d unchanged=%d failures=%d",
            report.rows,
            report.written,
            report.unchanged,
            len(report.failures),
        )
        return report
