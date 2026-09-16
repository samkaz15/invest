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
from mios.ingestion.verify import SourceVerifier

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
