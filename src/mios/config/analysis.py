"""Typed schema for ``config/analysis.yaml`` — the macro dimensions and the
two asset views.

``blind_spots`` is required on every dimension and every view, and validated
to be non-empty. That is unusual and deliberate: a yield-and-dollar model of
gold is not wrong, it is incomplete, and the incompleteness is not
discoverable from the output unless someone writes it down. Making it a
required field means nobody can add a dimension without stating what it
cannot see.
"""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from mios.common.ids import IdKind, pydantic_id_validator
from mios.common.schema import MiosModel

#: How a signal reads its series.
#:
#: ``level_z``  — the level itself, standardised (VIX is high or low).
#: ``change_z`` — period-over-period difference (yields moved).
#: ``trend_z``  — period-over-period percent change (prices are running).
Measure = Literal["level_z", "change_z", "trend_z"]


class SignalSpec(MiosModel):
    series_id: str
    label: str
    measure: Measure
    #: Points per standard deviation, signed. Negative where the series
    #: moves against the dimension — more jobless claims is a weaker labour
    #: market, so the weight carries the sign rather than the reader.
    weight: float
    min_history: int = Field(default=12, ge=4)

    @field_validator("series_id")
    @classmethod
    def _sid(cls, v: str) -> str:
        return pydantic_id_validator(v, IdKind.SERIES)


class DimensionSpec(MiosModel):
    dimension: str
    label: str
    #: (positive, neutral, negative) wording. A hawkish Fed and a bullish
    #: gold view are both positive scores; calling them the same thing would
    #: make every report read like it was written by something that did not
    #: understand either.
    stance_words: tuple[str, str, str]
    signals: list[SignalSpec] = Field(min_length=1)
    blind_spots: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_signals(self) -> "DimensionSpec":
        ids = [s.series_id for s in self.signals]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"{self.dimension}: duplicate signal {sorted(duplicates)}")
        return self


class ViewLink(MiosModel):
    """One step of the transmission chain into an asset."""

    dimension: str
    weight: float
    #: Why this dimension moves this asset, in a sentence. Required for the
    #: same reason driver weights need justifications: a chain nobody can
    #: defend is a correlation with a story attached.
    rationale: str = Field(min_length=10)


class AssetViewSpec(MiosModel):
    view_id: str
    asset_id: str
    label: str
    stance_words: tuple[str, str, str]
    links: list[ViewLink] = Field(min_length=1)
    blind_spots: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_links(self) -> "AssetViewSpec":
        names = [link.dimension for link in self.links]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"{self.view_id}: duplicate link {sorted(duplicates)}")
        return self


class AnalysisConfig(MiosModel):
    """config/analysis.yaml"""

    method_version: str
    dimensions: list[DimensionSpec] = Field(min_length=1)
    views: list[AssetViewSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _links_resolve(self) -> "AnalysisConfig":
        known = {d.dimension for d in self.dimensions}
        duplicates = {d for d in known if [x.dimension for x in self.dimensions].count(d) > 1}
        if duplicates:
            raise ValueError(f"duplicate dimension {sorted(duplicates)}")
        for view in self.views:
            unknown = [link.dimension for link in view.links if link.dimension not in known]
            if unknown:
                raise ValueError(f"{view.view_id} links to unknown dimension {sorted(unknown)}")
        return self

    def dimensions_by_id(self) -> dict[str, DimensionSpec]:
        return {d.dimension: d for d in self.dimensions}
