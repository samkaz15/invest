"""Raw payloads -> vintage-keyed observations.

This is the step BIOS got wrong. Its normalizer took the latest stored
payload for a source and wrote it as the current hour's value, so a source
that had been dead for three days still produced today's number
(docs/REPOSITORY_AUDIT.md §14 L4). Here, a value's vintage is the retrieval
time of the fetch that carried it — never the time normalization happened —
so stale data stays visibly stale instead of being relabelled as fresh.

One raw item can feed several series: the Treasury curve arrives as a single
CSV holding every tenor. Normalization is therefore driven by the series
registry, not by an assumption that one source means one series.
"""

from dataclasses import dataclass, field

from mios.common.logutil import get_logger
from mios.config.series import SeriesRegistry
from mios.ingestion.rawstore import RawStore
from mios.series.parsers import ParseError, get_parser
from mios.series.repo import NormalizeState, ObservationRepo
from mios.storage.db import Database

logger = get_logger(__name__)


@dataclass
class NormalizeReport:
    """What a normalization run did, including what it could not do."""

    raw_items: int = 0
    written: int = 0
    skipped: int = 0
    revisions: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


class Normalizer:
    def __init__(
        self,
        db: Database,
        store: RawStore,
        registry: SeriesRegistry,
        observations: ObservationRepo,
    ) -> None:
        self._store = store
        self._registry = registry
        self._observations = observations
        self._state = NormalizeState(db)

    def run(self, series_id: str | None = None) -> NormalizeReport:
        """Turn every unprocessed raw item into vintage-keyed rows.

        A parse failure is recorded and the run continues: one broken
        provider must not stop the other twenty. The failures land in the
        report, and the caller is expected to exit non-zero on them —
        a run that could not read its data is not a successful run.
        """
        report = NormalizeReport()
        done = self._state.processed()
        wanted = self._registry.series
        if series_id is not None:
            wanted = [s for s in wanted if s.series_id == series_id]
            if not wanted:
                report.failures.append(f"unknown series {series_id!r}")
                return report

        # Group by source so each raw item is read once even when several
        # series share it.
        by_source: dict[str, list[str]] = {}
        for spec in wanted:
            by_source.setdefault(spec.source_id, []).append(spec.series_id)

        registry = self._registry.by_id()
        for source_id, series_ids in sorted(by_source.items()):
            for item in self._store.items(source_id):
                touched = False
                for sid in series_ids:
                    if (item.raw_item_id, sid) in done:
                        continue
                    spec = registry[sid]
                    touched = True
                    try:
                        points = get_parser(spec.parser)(item.payload_text, spec)
                    except ParseError as exc:
                        # Loud and specific: the alternative is a silent
                        # zero-observation "success".
                        report.failures.append(f"{sid} <- {item.raw_item_id}: {exc}")
                        logger.error("parse failed for %s: %s", sid, exc)
                        continue
                    result = self._observations.write_points(
                        spec,
                        [(p.observation_date, p.value, p.vintage_at) for p in points],
                        raw_item_id=item.raw_item_id,
                        # Feeds that report when a value became public (ALFRED)
                        # carry their own vintage per point; the rest fall back
                        # to the fetch time.
                        default_vintage=item.retrieved_at,
                    )
                    self._state.mark(item.raw_item_id, sid, result.written, result.skipped)
                    report.written += result.written
                    report.skipped += result.skipped
                    report.revisions += result.revisions
                if touched:
                    report.raw_items += 1

        logger.info(
            "normalize: raw_items=%d written=%d unchanged=%d revisions=%d failures=%d",
            report.raw_items,
            report.written,
            report.skipped,
            report.revisions,
            len(report.failures),
        )
        return report
