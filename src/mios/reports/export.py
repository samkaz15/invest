"""CSV exports — the spreadsheet view of what MIOS has stored.

Why CSV rather than a real .xlsx, and why files rather than an API:

**PostgreSQL stays the master; the spreadsheet is a rendering.** A sheet
people can type into is a sheet whose history can be edited, and the whole
value of this project is that "what did we think ten days before the print"
cannot be quietly rewritten (CONSTITUTION.md Art.6-4). These files are
regenerated from the database every run, so a broken sheet costs nothing and
notes typed alongside are never mistaken for data.

**CSV needs no dependency and no credential.** Art.8 asks for an ADR before
a new package; openpyxl would buy formatting and cost a dependency, and the
Google Sheets API would additionally cost a service account and a secret.
Committed CSV opens directly in Excel *and* can be pulled live into a Google
Sheet with `=IMPORTDATA("<raw URL>")`, which refreshes itself whenever the
daily job commits. That is the same capability for none of the cost.

Files are written with a UTF-8 BOM. Excel on Windows reads a plain UTF-8 CSV
as Shift-JIS and turns every Japanese label into mojibake; the BOM is what
stops that, and Google Sheets ignores it.

Derived columns are computed here, at render time, from stored values — never
stored back. A month-over-month change kept in a second place is a second
truth, and two copies eventually disagree.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from mios.common.logutil import get_logger
from mios.config.loader import ConfigRoot
from mios.knowledge.store import CurationQueue
from mios.prediction.repo import ForecastRepo
from mios.series.calendar import CalendarRepo
from mios.series.repo import ObservationRepo
from mios.storage.db import Database

logger = get_logger(__name__)

#: Excel on Windows needs the BOM to read UTF-8; Sheets ignores it.
ENCODING = "utf-8-sig"


@dataclass(frozen=True)
class ExportedFile:
    path: Path
    rows: int


def _pct(new: Any, old: Any) -> str:
    """Month-over-month percent, or blank when either side is missing.

    Blank rather than 0: "we could not compute this" and "it did not move"
    are different facts, and a zero would read as the second.
    """
    if new is None or old is None:
        return ""
    try:
        previous = Decimal(str(old))
        if previous == 0:
            return ""
        return f"{(Decimal(str(new)) / previous - 1) * 100:.4f}"
    except (ArithmeticError, ValueError):
        return ""


def _num(value: Any, places: int = 6) -> str:
    return "" if value is None else f"{Decimal(str(value)):.{places}f}".rstrip("0").rstrip(".")


def _when(value: Any, precision: str = "exact") -> str:
    if value is None:
        return ""
    moment: datetime = value
    if precision == "date_only":
        # The provider gave a date. Printing 00:00 would invent an hour.
        return moment.date().isoformat()
    return moment.strftime("%Y-%m-%d %H:%M UTC")


class Exporter:
    """Writes every CSV. Reads stored rows and formats them; computes nothing else."""

    def __init__(self, db: Database, config: ConfigRoot, out_dir: Path) -> None:
        self._db = db
        self._config = config
        self._out = out_dir
        self._calendar = CalendarRepo(db)
        self._forecast_repo = ForecastRepo(db)
        self._observations = ObservationRepo(db)
        self._news = CurationQueue(db)

    def run(self, as_of: datetime) -> list[ExportedFile]:
        self._out.mkdir(parents=True, exist_ok=True)
        written = [
            self._write("releases.csv", *self._releases()),
            self._write("history.csv", *self._history(as_of)),
            self._write("calendar.csv", *self._calendar_rows(as_of)),
            self._write("forecasts.csv", *self._forecasts()),
            self._write("accuracy.csv", *self._accuracy()),
            self._write("series.csv", *self._series()),
            self._write("news.csv", *self._news_rows()),
        ]
        logger.info("export: %d file(s) to %s", len(written), self._out)
        return written

    def _write(self, name: str, header: list[str], rows: list[list[str]]) -> ExportedFile:
        path = self._out / name
        with path.open("w", encoding=ENCODING, newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        return ExportedFile(path=path, rows=len(rows))

    # ------------------------------------------------------------- releases

    def _releases(self) -> tuple[list[str], list[list[str]]]:
        """Every publication MIOS has recorded: the sheet to keep notes beside."""
        labels = {s.series_id: s.name for s in self._config.series.series}
        rows = self._db.query(
            """
            SELECT * FROM releases ORDER BY release_at DESC, series_id
            """
        )
        header = [
            "指標",
            "series_id",
            "参照期間",
            "発表日時(UTC)",
            "actual",
            "前月比%",
            "事前予想(機関)",
            "サプライズ",
            "previous",
            "revised_previous",
            "改定あり",
            "単位",
            "出典",
        ]
        out: list[list[str]] = []
        for row in rows:
            revised = (
                row["previous"] is not None
                and row["revised_previous"] is not None
                and row["previous"] != row["revised_previous"]
            )
            out.append(
                [
                    labels.get(row["series_id"], row["series_id"]),
                    row["series_id"],
                    row["period"].isoformat(),
                    _when(row["release_at"]),
                    _num(row["actual"]),
                    # Against the *revised* previous, which is what the
                    # agency's own published change is computed from.
                    # `previous` is kept beside it as what the market had
                    # been comparing against, and the two differ exactly
                    # when the release revised history.
                    _pct(row["actual"], row["revised_previous"]),
                    _num(row["forecast"]),
                    _num(row["surprise"]),
                    _num(row["previous"]),
                    _num(row["revised_previous"]),
                    "yes" if revised else "",
                    row["basis"],
                    row["source_url"],
                ]
            )
        return header, out

    # -------------------------------------------------------------- history

    def _history(self, as_of: datetime) -> tuple[list[str], list[list[str]]]:
        """Every series' level history with its period-over-period change.

        Separate from releases.csv, and the separation is the point. Most of
        this arrived in one backfill, so MIOS cannot say when any of it was
        published — only what the figures are. Putting it in the releases
        sheet would stamp each row with the download time and assert a
        publication date nobody announced.

        So: releases.csv is what MIOS watched happen and starts nearly
        empty, growing one row per print. history.csv is the numbers, all of
        them, from the first day.

        Read through the repository at an explicit instant, like every other
        read of a revisable series. An export is "as of now", and saying so
        costs one argument and keeps the rule without an exception.
        """
        header = [
            "指標",
            "series_id",
            "参照期間",
            "値",
            "前期比%",
            "この値の vintage",
            "改定回数",
        ]
        out: list[list[str]] = []
        for spec in self._config.series.series:
            rows = self._observations.as_of(spec.series_id, as_of)
            previous: Any = None
            for row in rows:
                out.append(
                    [
                        spec.name,
                        spec.series_id,
                        row.observation_date.isoformat(),
                        _num(row.value),
                        _pct(row.value, previous),
                        _when(row.vintage_at),
                        str(row.revision_n),
                    ]
                )
                if row.value is not None:
                    previous = row.value
        return header, out

    # ------------------------------------------------------------- calendar

    def _calendar_rows(self, as_of: datetime) -> tuple[list[str], list[list[str]]]:
        labels = {s.series_id: s.name for s in self._config.series.series}
        rows = self._calendar.upcoming(as_of, limit=200)
        header = [
            "発表予定(UTC)",
            "時刻の確度",
            "発表名",
            "指標",
            "series_id",
            "重要度",
            "国",
            "状態",
        ]
        return header, [
            [
                _when(row["scheduled_at"], row["time_precision"]),
                "確定" if row["time_precision"] == "exact" else "日付のみ",
                row["title"],
                labels.get(row["series_id"], "") if row["series_id"] else "",
                row["series_id"] or "",
                str(row["importance"]),
                row["country"],
                row["status"],
            ]
            for row in rows
        ]

    # ------------------------------------------------------------ forecasts

    def _forecasts(self) -> tuple[list[str], list[list[str]]]:
        """Every forecast vintage. The column that makes this worth keeping
        is `予測日` — the same target period appears many times, once per day."""
        rows = self._forecast_repo.all_with_scores()
        header = [
            "series_id",
            "対象期間",
            "予測日",
            "予測",
            "ナイーブ基準",
            "調整幅",
            "上振れ確率",
            "確信度",
            "実績(初回発表)",
            "誤差",
            "skill",
            "方向的中",
            "method",
        ]
        out: list[list[str]] = []
        for row in rows:
            point = row["point_value"]
            baseline = row["baseline_value"]
            adjustment = (
                _num(Decimal(str(point)) - Decimal(str(baseline)))
                if point is not None and baseline is not None
                else ""
            )
            hit = row["direction_hit"]
            out.append(
                [
                    row["target_series_id"],
                    row["target_period"].isoformat(),
                    row["predicted_at"].date().isoformat(),
                    _num(point),
                    _num(baseline),
                    adjustment,
                    _num(row["upside_prob"], places=3),
                    _num(row["confidence"], places=2),
                    _num(row["actual"]),
                    _num(row["error"]),
                    _num(row["skill"]),
                    "" if hit is None else ("yes" if hit else "no"),
                    row["method_version"],
                ]
            )
        return header, out

    # ------------------------------------------------------------- accuracy

    def _accuracy(self) -> tuple[list[str], list[list[str]]]:
        rows = self._db.query(
            """
            SELECT target_series_id, target_period, days_ahead, actual, point_value,
                   baseline_value, error, abs_error, baseline_error, skill, direction_hit
            FROM forecast_errors ORDER BY target_series_id, target_period, days_ahead
            """
        )
        header = [
            "series_id",
            "対象期間",
            "何日前",
            "実績",
            "予測",
            "ナイーブ",
            "誤差",
            "絶対誤差",
            "ナイーブ誤差",
            "skill",
            "方向的中",
        ]
        return header, [
            [
                row["target_series_id"],
                row["target_period"].isoformat(),
                str(row["days_ahead"]),
                _num(row["actual"]),
                _num(row["point_value"]),
                _num(row["baseline_value"]),
                _num(row["error"]),
                _num(row["abs_error"]),
                _num(row["baseline_error"]),
                _num(row["skill"]),
                "" if row["direction_hit"] is None else ("yes" if row["direction_hit"] else "no"),
            ]
            for row in rows
        ]

    # ----------------------------------------------------------------- news

    def _news_rows(self) -> tuple[list[str], list[list[str]]]:
        """Collected headlines with their source tier.

        The tier column is the important one. A Tier 3 headline is a report,
        not a fact, and a spreadsheet that lost that distinction would make
        every row look equally solid (CONSTITUTION.md Art.4).
        """
        tiers = {sid: spec.tier for sid, spec in self._config.sources.items()}
        header = ["取得日時(UTC)", "tier", "ソース", "見出し", "配信元の公開日時", "URL"]
        rows = self._news.pending(limit=1000)
        return header, [
            [
                _when(row["created_at"]),
                f"T{tiers.get(row['source_id'], row['payload'].get('tier', 4))}",
                row["source_id"],
                row["payload"].get("title") or "",
                row["payload"].get("published_raw") or "",
                row["payload"].get("link") or "",
            ]
            for row in rows
        ]

    # --------------------------------------------------------------- series

    def _series(self) -> tuple[list[str], list[list[str]]]:
        """The registry beside what has actually been collected.

        A series with zero vintages prints as a gap rather than as a blank
        line that looks like data nobody happened to fill in.
        """
        coverage = {row["series_id"]: row for row in self._observations.coverage()}
        header = [
            "series_id",
            "名称",
            "国",
            "分類",
            "単位",
            "頻度",
            "ソース",
            "provider_code",
            "観測数",
            "最新参照期間",
            "最終取得",
            "状態",
        ]
        out: list[list[str]] = []
        for spec in self._config.series.series:
            row = coverage.get(spec.series_id)
            out.append(
                [
                    spec.series_id,
                    spec.name,
                    spec.country,
                    spec.category,
                    spec.unit,
                    spec.frequency,
                    spec.source_id,
                    spec.provider_code,
                    str(row["vintages"]) if row else "0",
                    row["latest_period"].isoformat() if row and row["latest_period"] else "",
                    _when(row["latest_vintage"]) if row and row["latest_vintage"] else "",
                    "取得済" if row and int(row["vintages"]) else "未取得",
                ]
            )
        return header, out
