"""Check every configured source against the live provider, and store nothing.

This exists because a large part of the configuration was written without
network access: FRED series ids, the Treasury CSV's column names, Twelve
Data's response shape and the MOF file's layout are all *plausible* rather
than confirmed (docs/ARCHITECTURE.md §6 A-3). Every one of them fails loudly
rather than silently, so nothing here can produce bad data — but "fails
loudly at 07:10 every morning" is a bad way to find out.

A dry run: it fetches, parses, and reports. Nothing is written to the raw
store or the database, so this is safe to run against production credentials
at any time, and running it twice costs nothing but two API calls.

The parse step is the point. A source that returns HTTP 200 and a payload
the parser cannot read is worse than one that is simply down, because only
the parser notices.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from mios.common.errors import MiosError
from mios.common.logutil import get_logger
from mios.config.models import SourceSpec
from mios.config.series import SeriesRegistry
from mios.ingestion.adapter import AdapterError, SourceAdapter
from mios.ingestion.adapters import build_adapter
from mios.ingestion.http import HttpClient, TransportError
from mios.series.parsers import ParseError, get_parser

logger = get_logger(__name__)


@dataclass
class SeriesCheck:
    series_id: str
    ok: bool
    detail: str
    points: int = 0


@dataclass(frozen=True)
class ExtraParse:
    """A parse check this module cannot reach for itself.

    Some sources carry no time series at all — an institutional forecast
    file is read by the prediction layer, which imports ingestion and so
    cannot be imported back. Without this the verifier would fetch such a
    source, find no series pointing at it, and report it healthy on an HTTP
    200 alone — which is precisely the check that does not catch a renamed
    column.

    So the composition root injects the parse. ``parse`` takes the payload
    and returns how many usable values it found, raising on failure.
    """

    label: str
    parse: Callable[[str], int]


@dataclass
class SourceCheck:
    source_id: str
    name: str
    tier: int
    #: None when the source is disabled — a missing key is a configuration
    #: state, not a provider failure, and conflating them would hide both.
    reachable: bool | None
    detail: str
    series: list[SeriesCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.reachable is True and all(check.ok for check in self.series)

    @property
    def skipped(self) -> bool:
        return self.reachable is None


@dataclass
class VerifyReport:
    checks: list[SourceCheck] = field(default_factory=list)

    @property
    def failures(self) -> list[SourceCheck]:
        return [c for c in self.checks if not c.ok and not c.skipped]

    @property
    def skipped(self) -> list[SourceCheck]:
        return [c for c in self.checks if c.skipped]

    @property
    def ok(self) -> bool:
        return not self.failures


class SourceVerifier:
    def __init__(
        self,
        sources: dict[str, SourceSpec],
        registry: SeriesRegistry,
        client: HttpClient | None = None,
        adapter_factory: Callable[[SourceSpec], SourceAdapter] = build_adapter,
        extra: dict[str, list[ExtraParse]] | None = None,
    ) -> None:
        self._sources = sources
        self._registry = registry
        self._client = client or HttpClient()
        self._adapter = adapter_factory
        self._extra = extra or {}

    def check(self, source_id: str | None = None) -> VerifyReport:
        report = VerifyReport()
        wanted = (
            {source_id: self._sources[source_id]}
            if source_id and source_id in self._sources
            else self._sources
        )
        for sid, spec in sorted(wanted.items()):
            report.checks.append(self._check_one(sid, spec))
        logger.info(
            "verify: %d checked, %d failed, %d skipped",
            len(report.checks),
            len(report.failures),
            len(report.skipped),
        )
        return report

    def _check_one(self, source_id: str, spec: SourceSpec) -> SourceCheck:
        if not spec.enabled:
            return SourceCheck(
                source_id=source_id,
                name=spec.name,
                tier=spec.tier,
                reachable=None,
                detail="disabled (missing credential, or turned off in config)",
            )

        try:
            result = self._adapter(spec).fetch(self._client)
        except (AdapterError, TransportError) as exc:
            return SourceCheck(
                source_id=source_id,
                name=spec.name,
                tier=spec.tier,
                reachable=False,
                detail=str(exc),
            )

        if result.not_modified:
            # Only possible with a conditional header, which a dry run does
            # not send; treat it as a fetch that told us nothing.
            return SourceCheck(
                source_id=source_id,
                name=spec.name,
                tier=spec.tier,
                reachable=True,
                detail="304 Not Modified (nothing to parse)",
            )
        if not result.drafts:
            return SourceCheck(
                source_id=source_id,
                name=spec.name,
                tier=spec.tier,
                reachable=False,
                detail="fetch succeeded but returned no payload",
            )

        payload = result.drafts[0].payload_text
        checks: list[SeriesCheck] = []
        for extra in self._extra.get(source_id, []):
            try:
                found = extra.parse(payload)
            except MiosError as exc:
                checks.append(SeriesCheck(extra.label, False, str(exc)))
                continue
            checks.append(SeriesCheck(extra.label, True, f"{found} value(s)", found))
        for series_spec in self._registry.for_source(source_id):
            try:
                points = get_parser(series_spec.parser)(payload, series_spec)
            except ParseError as exc:
                checks.append(SeriesCheck(series_spec.series_id, False, str(exc)))
                continue
            usable = [p for p in points if p.value is not None]
            if not usable:
                # A parse that yields nothing usable is a failure, not an
                # empty day: it means the id or the column is wrong.
                checks.append(
                    SeriesCheck(
                        series_spec.series_id,
                        False,
                        f"parsed {len(points)} row(s) but none carried a value "
                        "— check provider_code",
                        len(points),
                    )
                )
                continue
            latest = max(p.observation_date for p in usable)
            checks.append(
                SeriesCheck(
                    series_spec.series_id,
                    True,
                    f"{len(usable)} value(s), latest {latest.isoformat()}",
                    len(usable),
                )
            )

        return SourceCheck(
            source_id=source_id,
            name=spec.name,
            tier=spec.tier,
            reachable=True,
            detail=f"{len(payload):,} bytes",
            series=checks,
        )
