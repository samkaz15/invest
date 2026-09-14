"""Typed schema for ``config/series.yaml`` — the registry of tracked series."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from mios.common.ids import IdKind, pydantic_id_validator
from mios.common.labels import Country, Frequency
from mios.common.schema import MiosModel

Category = Literal["inflation", "employment", "growth", "rates", "fx", "commodity", "risk"]
Unit = Literal["percent", "percent_change", "index", "thousands", "level", "ratio"]
SeasonalAdjustment = Literal["sa", "nsa", "unknown", "not_applicable"]


class SeriesSpec(MiosModel):
    """One tracked time series.

    ``parser`` names a payload reader, not a provider: several sources can
    speak the same shape (every FRED endpoint does), and a series only needs
    to say which shape to expect.
    """

    series_id: str
    name: str
    country: Country
    category: Category
    unit: Unit
    frequency: Frequency
    source_id: str
    provider_code: str  # the identifier at the provider: CPIAUCSL, "10 Yr", XAU/USD
    parser: str
    revisable: bool
    seasonal_adjustment: SeasonalAdjustment = "unknown"
    notes: str = ""

    @field_validator("series_id")
    @classmethod
    def _sid(cls, v: str) -> str:
        return pydantic_id_validator(v, IdKind.SERIES)

    @field_validator("source_id")
    @classmethod
    def _src(cls, v: str) -> str:
        return pydantic_id_validator(v, IdKind.SOURCE)

    @field_validator("provider_code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("provider_code cannot be blank")
        return v

    @model_validator(mode="after")
    def _daily_series_are_not_revisable(self) -> "SeriesSpec":
        """Market quotes and constant-maturity yields are published once.

        Marking one revisable would be harmless; marking a revised series
        non-revisable is not, because it invites reading it without an
        as-of filter. So the cheap half of the check is enforced here and
        the expensive half stays a human decision.
        """
        if self.revisable and self.category in ("fx", "commodity", "risk"):
            raise ValueError(
                f"{self.series_id}: price series are not revised; "
                "revisable=true suggests a category or a copy-paste mistake"
            )
        return self


class SeriesRegistry(MiosModel):
    """config/series.yaml"""

    series: list[SeriesSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> "SeriesRegistry":
        ids = [s.series_id for s in self.series]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate series_id: {sorted(duplicates)}")
        return self

    def by_id(self) -> dict[str, SeriesSpec]:
        return {s.series_id: s for s in self.series}

    def for_source(self, source_id: str) -> list[SeriesSpec]:
        """Every series carried by one source's payload.

        One fetch can produce many series (the Treasury curve is a single
        CSV holding the whole curve), so normalization is driven from here
        rather than assuming one source means one series.
        """
        return [s for s in self.series if s.source_id == source_id]
