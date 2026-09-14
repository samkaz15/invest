"""The arithmetic behind a forecast, without a database.

Two things are being pinned down. First, that the probabilities mean
something measurable — BIOS produced them by a linear transform of a score,
and measuring the calibration of that would have measured the slope of a
formula (docs/REPOSITORY_AUDIT.md §8 U-12). Second, that thin history
produces `None` rather than a confident-looking number, because a forecast
built from four observations that does not say so is worse than no forecast
at all.
"""

from datetime import date

import pytest

from mios.prediction.features import (
    Series,
    deviation_from_trend,
    diff_series,
    mom_series,
    next_period,
    trailing_mean,
    zscore,
)
from mios.prediction.probability import (
    MIN_ERROR_SAMPLE,
    baseline_error_spread,
    confidence_from,
    directional_probabilities,
    normal_cdf,
)


def _series(values: list[float]) -> Series:
    return Series(
        series_id="ser_us_cpi_index",
        periods=[date(2026, 1, 1) for _ in values],
        values=values,
    )


# --------------------------------------------------------------- features


def test_mom_series_is_fractional_not_percentage_points() -> None:
    """A 1% rise is 0.01, so an elastic weight is a plain basket share."""
    assert mom_series(_series([100.0, 101.0])) == [pytest.approx(0.01)]


def test_diff_series_keeps_levels_for_counts() -> None:
    assert diff_series(_series([150000.0, 150180.0])) == [pytest.approx(180.0)]


def test_deviation_from_trend_measures_the_latest_against_its_own_history() -> None:
    values = [0.002] * 12 + [0.005]
    assert deviation_from_trend(values, window=12) == pytest.approx(0.003)


def test_features_return_none_on_thin_history_rather_than_guessing() -> None:
    assert deviation_from_trend([0.002, 0.003]) is None
    assert zscore([0.002, 0.003]) is None
    assert trailing_mean([0.002], window=3) is None


def test_zscore_is_none_when_history_never_moves() -> None:
    """A flat series has no scale to be unusual against, so there is no
    standardised reading to give — not a zero, which would read as "normal"."""
    assert zscore([1.0] * 12) is None


def test_next_period_steps_months_and_wraps_the_year() -> None:
    assert next_period(date(2026, 8, 1), "monthly") == date(2026, 9, 1)
    assert next_period(date(2026, 12, 1), "monthly") == date(2027, 1, 1)
    assert next_period(date(2026, 10, 1), "quarterly") == date(2027, 1, 1)


def test_next_period_refuses_a_frequency_it_cannot_step() -> None:
    with pytest.raises(ValueError, match="daily"):
        next_period(date(2026, 9, 11), "daily")


# ---------------------------------------------------------- probabilities


def test_normal_cdf_matches_known_values() -> None:
    assert normal_cdf(0.0) == pytest.approx(0.5)
    assert normal_cdf(1.0) == pytest.approx(0.8413, abs=1e-4)
    assert normal_cdf(-1.96) == pytest.approx(0.025, abs=1e-3)


def test_baseline_error_spread_is_measured_from_replayed_history() -> None:
    """The spread is what the naive forecast has actually been wrong by.

    A series that alternates cannot be predicted by its own trailing mean,
    so its baseline errors are large — and a small driver push should mean
    little against it.
    """
    alternating = [0.0, 0.4] * 12
    spread = baseline_error_spread(alternating, window=3)
    assert spread is not None and spread > 0.1


def test_baseline_error_spread_withholds_a_number_on_thin_history() -> None:
    assert baseline_error_spread([0.1, 0.2, 0.3, 0.4], window=3) is None
    barely_short = [0.1 * i for i in range(3 + MIN_ERROR_SAMPLE - 1)]
    assert baseline_error_spread(barely_short, window=3) is None


def test_a_perfectly_predictable_series_has_no_usable_spread() -> None:
    """Zero spread would make every probability 0 or 1.

    That is not confidence, it is an artefact of a toy series, so no
    probability is offered at all.
    """
    assert baseline_error_spread([0.2] * 30, window=3) is None


def test_probabilities_are_withheld_when_the_spread_is_unknown() -> None:
    """An unknown probability is a real answer; 50% would be a made-up one."""
    assert directional_probabilities(0.1, None) == (None, None)


def test_probabilities_scale_with_the_push_relative_to_the_spread() -> None:
    """Same push, wider historical error, weaker claim."""
    tight_up, tight_down = directional_probabilities(0.1, 0.05)
    loose_up, loose_down = directional_probabilities(0.1, 0.5)
    assert tight_up is not None and loose_up is not None
    assert tight_up > loose_up > 0.5
    assert tight_down is not None and loose_down is not None
    assert tight_up + tight_down == pytest.approx(1.0)


def test_no_push_means_an_even_split() -> None:
    assert directional_probabilities(0.0, 0.1) == (0.5, 0.5)


# ------------------------------------------------------------ confidence


def test_confidence_falls_when_inputs_are_missing() -> None:
    full = confidence_from(available=6, missing=0, history=60, needed=6)
    half = confidence_from(available=3, missing=3, history=60, needed=6)
    assert full > half


def test_confidence_falls_when_history_is_short() -> None:
    deep = confidence_from(available=6, missing=0, history=60, needed=24)
    shallow = confidence_from(available=6, missing=0, history=6, needed=24)
    assert deep > shallow


def test_confidence_never_claims_certainty_or_reaches_zero() -> None:
    """A floor because a forecast that exists has *some* basis; a ceiling
    because no method built on seven indicators is 100% trustworthy."""
    assert confidence_from(available=0, missing=9, history=0, needed=24) == 0.1
    assert confidence_from(available=99, missing=0, history=999, needed=1) <= 0.95


def test_probabilities_never_claim_certainty() -> None:
    """A method with uncalibrated, prior-based weights has not earned 99%.

    The normal assumption is thinnest exactly in the tails, and nothing here
    has been checked against a single realised outcome yet, so the extremes
    are bounded (CONSTITUTION.md Art.5 forbids stating a forecast as a
    certainty). The bound relaxes when there is calibration evidence to
    relax it with.
    """
    from mios.prediction.probability import PROBABILITY_BOUND

    up, down = directional_probabilities(10.0, 0.01)  # a 1000-sigma push
    assert up == pytest.approx(1 - PROBABILITY_BOUND)
    assert down == pytest.approx(PROBABILITY_BOUND)

    up, down = directional_probabilities(-10.0, 0.01)
    assert up == pytest.approx(PROBABILITY_BOUND)
    assert down == pytest.approx(1 - PROBABILITY_BOUND)
