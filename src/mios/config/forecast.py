"""Typed schema for ``config/forecast.yaml`` — what each target is built from.

The weights live in configuration, not in code, for the same reason the
scoring weights do: changing one has to be a reviewable diff, and every
stored forecast records the ``method_version`` that produced it, so an old
forecast stays interpretable after the weights move.
"""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from mios.common.ids import IdKind, pydantic_id_validator
from mios.common.labels import Frequency
from mios.common.schema import MiosModel

#: How a driver's reading converts into the target's units.
#:
#: ``elastic``  — the driver is a share of the target by construction (a
#:                basket weight), so its own percent move converts directly.
#: ``standard`` — no natural conversion exists, so the reading is expressed
#:                in standard deviations and converted by a prior. These are
#:                the weights most in need of re-estimation once forecast
#:                errors accumulate, and `justification` must say so.
DriverMode = Literal["elastic", "standard"]


class DriverSpec(MiosModel):
    series_id: str
    label: str
    mode: DriverMode
    weight: float
    #: What the driver's raw values must be turned into before reading:
    #: a percent change, a level difference, or the level itself.
    transform: Literal["pct_change", "diff", "level"] = "pct_change"
    window: int = Field(default=12, ge=2)
    #: Why this weight, in one sentence. Required: a weight nobody can
    #: defend is the untraceable score this project already deleted once
    #: (docs/REPOSITORY_AUDIT.md §8 U-12).
    justification: str = Field(min_length=10)

    @field_validator("series_id")
    @classmethod
    def _sid(cls, v: str) -> str:
        return pydantic_id_validator(v, IdKind.SERIES)


class TargetSpec(MiosModel):
    """One thing MIOS forecasts."""

    series_id: str
    label: str
    frequency: Frequency
    #: What is actually forecast: the period-over-period percent change of
    #: an index, or the difference in a level (payrolls).
    transform: Literal["pct_change", "diff"]
    unit_label: str  # for human-readable rationales, e.g. "pp" or "k jobs"
    #: Periods behind the naive benchmark. Also the window whose replayed
    #: errors give the probability spread.
    baseline_window: int = Field(default=3, ge=2)
    #: Hard bound on how far the drivers may move the call away from the
    #: baseline. One wild reading must not drag the forecast further than
    #: the method can justify.
    max_adjustment: float = Field(gt=0)
    drivers: list[DriverSpec] = Field(min_length=1)

    @field_validator("series_id")
    @classmethod
    def _sid(cls, v: str) -> str:
        return pydantic_id_validator(v, IdKind.SERIES)

    @model_validator(mode="after")
    def _unique_drivers(self) -> "TargetSpec":
        ids = [d.series_id for d in self.drivers]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"{self.series_id}: duplicate driver {sorted(duplicates)}")
        if self.series_id in ids:
            raise ValueError(f"{self.series_id}: a target cannot be its own driver")
        return self


class ForecastConfig(MiosModel):
    """config/forecast.yaml"""

    method_version: str
    targets: list[TargetSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_targets(self) -> "ForecastConfig":
        ids = [t.series_id for t in self.targets]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate forecast target {sorted(duplicates)}")
        return self

    def by_id(self) -> dict[str, TargetSpec]:
        return {t.series_id: t for t in self.targets}
