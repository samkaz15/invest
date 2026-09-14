"""The source verifier, exercised without a network.

The verifier exists to answer a question this environment cannot: are the
FRED series ids, the Treasury column names and the vendor response shapes
actually right? Its own logic can still be proven here, by feeding it stub
adapters that return the payloads a provider would.

What matters is that it distinguishes three states that look alike from a
distance: a source that is down, a source that answered with something the
parser cannot read, and a source nobody asked to run because its credential
is unset. Collapsing any two of those hides both.
"""

from pathlib import Path

from mios.config.loader import load_config
from mios.config.models import SourceSpec
from mios.ingestion.adapter import AdapterError, FetchResult, HttpGetter, SourceAdapter
from mios.ingestion.http import TransportError
from mios.ingestion.rawitem import RawDraft
from mios.ingestion.verify import ExtraParse, SourceVerifier
from mios.prediction.external import get_external_parser

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"
CPI_SOURCE = "src_fred_cpiaucsl"


def _config():  # type: ignore[no-untyped-def]
    return load_config(REPO / "config")


class _Stub(SourceAdapter):
    """An adapter that replays a canned payload, or a canned failure."""

    payload: str | None = None
    error: Exception | None = None

    def fetch(self, client: HttpGetter, conditional: dict[str, str] | None = None) -> FetchResult:
        if self.error is not None:
            raise self.error
        assert self.payload is not None
        return FetchResult(
            drafts=[RawDraft(payload_text=self.payload, content_type="application/json")]
        )


def _verifier(payload: str | None = None, error: Exception | None = None) -> SourceVerifier:
    config = _config()

    def factory(spec: SourceSpec) -> SourceAdapter:
        stub = _Stub(spec)
        stub.payload = payload
        stub.error = error
        return stub

    sources = {CPI_SOURCE: config.sources[CPI_SOURCE]}
    return SourceVerifier(sources, config.series, adapter_factory=factory)


def test_a_good_payload_reports_the_series_and_its_latest_period() -> None:
    payload = (FIXTURES / "fred_cpiaucsl.json").read_text(encoding="utf-8")
    report = _verifier(payload=payload).check()

    assert report.ok
    [check] = report.checks
    assert check.reachable is True
    [series] = check.series
    assert series.ok
    assert "latest 2026-08-01" in series.detail


def test_an_unreachable_source_is_a_failure_with_the_reason_attached() -> None:
    report = _verifier(error=TransportError("HTTP 403 from api.stlouisfed.org")).check()
    assert not report.ok
    [check] = report.checks
    assert check.reachable is False
    assert "403" in check.detail


def test_a_reachable_source_whose_payload_cannot_be_parsed_still_fails() -> None:
    """The case that matters most, and the one a plain health check misses.

    HTTP 200 plus a body the parser cannot read is worse than a source being
    down, because only the parser notices.
    """
    report = _verifier(payload='{"note": "we restructured our API"}').check()
    assert not report.ok
    [check] = report.checks
    assert check.reachable is True  # the fetch worked
    [series] = check.series
    assert not series.ok
    assert "no 'observations' list" in series.detail


def test_a_wrong_series_id_shows_up_as_no_usable_values() -> None:
    """FRED answers a bad series id with an error body rather than a 404.

    Either way the verifier must not call it healthy — this is exactly the
    mistake the configuration is most likely to contain.
    """
    report = _verifier(payload='{"error_code": 400, "error_message": "Bad Request."}').check()
    assert not report.ok
    [series] = report.checks[0].series
    assert "FRED error" in series.detail


def test_an_empty_but_valid_payload_is_a_failure_not_an_empty_day() -> None:
    report = _verifier(payload='{"observations": []}').check()
    assert not report.ok
    [series] = report.checks[0].series
    assert "check provider_code" in series.detail


def test_a_payload_of_only_published_gaps_is_a_failure() -> None:
    """All-null rows mean the id or the column is wrong, not that the agency
    published nothing for two years."""
    payload = '{"observations": [{"date": "2026-08-01", "value": "."}]}'
    report = _verifier(payload=payload).check()
    assert not report.ok


def test_a_source_without_its_credential_is_skipped_not_failed() -> None:
    """A missing key is a configuration state, not a provider outage.

    Reporting it as a failure would bury the real failures; reporting it as
    a success would hide the gap. It is its own category.
    """
    config = _config()
    disabled = config.sources[CPI_SOURCE].model_copy(update={"enabled": False})
    verifier = SourceVerifier({CPI_SOURCE: disabled}, config.series)

    report = verifier.check()
    assert report.ok  # nothing is broken
    assert len(report.skipped) == 1
    assert "missing credential" in report.skipped[0].detail


def test_an_adapter_error_is_caught_rather_than_crashing_the_run() -> None:
    """One malformed provider must not stop the other forty being checked."""
    report = _verifier(error=AdapterError("non-JSON response")).check()
    assert not report.ok
    assert report.checks[0].reachable is False


def test_the_verifier_covers_every_configured_source() -> None:
    config = _config()
    verifier = SourceVerifier(config.sources, config.series)
    # Nothing is fetched here: every source is disabled without credentials
    # in this environment, which is itself the assertion that the command
    # walks the whole registry.
    report = verifier.check()
    assert len(report.checks) == len(config.sources)


# ------------------------------------------------- injected forecast checks


def _forecast_verifier(payload: str) -> SourceVerifier:
    """A verifier for a source that carries no time series at all."""
    config = _config()
    provider = config.external.providers[0]
    target = provider.targets[0]
    reader = get_external_parser(provider.parser)

    def factory(spec: SourceSpec) -> SourceAdapter:
        stub = _Stub(spec)
        stub.payload = payload
        return stub

    return SourceVerifier(
        # Enabled explicitly: the source is switched off in config while its
        # download URL is unknown (it 404'd in the first real run), but what
        # is under test here is the parse path, not that switch.
        {
            provider.provider_id: config.sources[provider.provider_id].model_copy(
                update={"enabled": True}
            )
        },
        config.series,
        adapter_factory=factory,
        extra={
            provider.provider_id: [
                ExtraParse(
                    label=target.target_series_id,
                    parse=lambda text: len(reader(text, provider, target)),
                )
            ]
        },
    )


def test_a_forecast_file_is_parsed_rather_than_merely_reached() -> None:
    """No series points at an institutional forecast file.

    Without an injected parse check the verifier would fetch it, find
    nothing to read, and report it healthy on an HTTP 200 alone — which is
    exactly the check that fails to notice a renamed column.
    """
    report = _forecast_verifier("Date,CPI,Core CPI\n2026-08-01,0.31,0.28\n").check()
    [check] = report.checks
    assert check.ok
    assert check.series and check.series[0].points == 1


def test_a_forecast_file_that_answers_200_with_the_wrong_columns_fails() -> None:
    report = _forecast_verifier("Date,Headline,Core\n2026-08-01,0.31,0.28\n").check()
    [check] = report.checks
    assert check.reachable is True  # it answered
    assert not check.ok  # but it did not answer with what config expects
    assert "columns present" in check.series[0].detail


def test_a_feed_reports_how_many_entries_came_back_not_one_entry_s_size() -> None:
    """The first real verification run made healthy feeds look broken.

    A feed adapter splits its response into one draft per article, and the
    verifier was reporting the size of draft zero — so a working Fed press
    feed showed as "540 bytes" and read like an error page. What a reader
    needs from a feed is the entry count, because a feed that has quietly
    become empty is the failure a byte count cannot show.
    """
    config = _config()
    spec = config.sources["src_fed_press"]

    class _Feed(SourceAdapter):
        def fetch(
            self, client: HttpGetter, conditional: dict[str, str] | None = None
        ) -> FetchResult:
            return FetchResult(
                drafts=[
                    RawDraft(payload_text='{"title": "a"}', content_type="application/json"),
                    RawDraft(payload_text='{"title": "b"}', content_type="application/json"),
                    RawDraft(payload_text='{"title": "c"}', content_type="application/json"),
                ]
            )

    verifier = SourceVerifier(
        {"src_fed_press": spec}, config.series, adapter_factory=lambda s: _Feed(s)
    )
    [check] = verifier.check().checks
    assert check.ok
    assert check.detail == "3 entrie(s)"
