"""Typed schema for ``config/external.yaml`` — whose forecasts MIOS is measured against.

An outside forecast is only comparable to MIOS's own if it is expressed in
the same units, and the conversion is where a silent, invisible error lives:
a nowcast published as "0.28" meaning 0.28 percent must become 0.0028 before
it can be subtracted from a MIOS point value, and nothing downstream would
notice a factor of a hundred — the comparison would simply report that the
Cleveland Fed is catastrophically bad at its own job.

So the scale is stated per target, the publisher's unit is named, and the
raw figure is stored next to the converted one. Getting it wrong stays
detectable after the fact instead of turning into a flattering verdict.
"""

from pydantic import Field, field_validator, model_validator

from mios.common.ids import IdKind, pydantic_id_validator
from mios.common.schema import MiosModel


class ExternalTargetSpec(MiosModel):
    """One target an outside provider publishes a forecast for."""

    target_series_id: str
    #: How this provider names the target in its payload — the row or column
    #: key. Wrong values fail loudly at parse time, never silently.
    provider_code: str
    #: The publisher's own unit, recorded verbatim so the stored raw_value
    #: stays interpretable without reading their website again.
    raw_unit: str = Field(min_length=2)
    #: Multiplier taking the published figure into the target's forecasting
    #: units. 0.01 for a figure published in percent against a target
    #: forecast as a fraction; 1.0 when the units already agree.
    scale: float = Field(gt=0)

    @field_validator("target_series_id")
    @classmethod
    def _sid(cls, v: str) -> str:
        return pydantic_id_validator(v, IdKind.SERIES)


class ProviderSpec(MiosModel):
    """An institution whose published forecasts MIOS stores and scores."""

    provider_id: str  # must also exist as a collectable source
    label: str
    parser: str  # a reader in src/mios/prediction/external.py
    #: Where a reader can go and check the number. Stored on every row
    #: (指示書 §26), so it is required here rather than optional.
    source_url: str = Field(min_length=8)
    method: str = Field(min_length=10)
    targets: list[ExternalTargetSpec] = Field(min_length=1)

    @field_validator("provider_id")
    @classmethod
    def _pid(cls, v: str) -> str:
        return pydantic_id_validator(v, IdKind.SOURCE)

    @model_validator(mode="after")
    def _unique_targets(self) -> "ProviderSpec":
        ids = [t.target_series_id for t in self.targets]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"{self.provider_id}: duplicate target {sorted(duplicates)}")
        return self


class ExternalConfig(MiosModel):
    #: Targets MIOS forecasts that no free, machine-readable institutional
    #: forecast covers. Required, and validated as non-empty, for the same
    #: reason every score must declare its blind spots: a scoreboard showing
    #: two of four targets reads as a complete scoreboard unless it says
    #: otherwise. See config/external.yaml for why each one is here.
    uncovered: list[str] = Field(min_length=1)
    providers: list[ProviderSpec] = Field(default_factory=list)

    def by_id(self) -> dict[str, ProviderSpec]:
        return {p.provider_id: p for p in self.providers}

    def for_target(self, target_series_id: str) -> list[ProviderSpec]:
        return [
            p
            for p in self.providers
            if any(t.target_series_id == target_series_id for t in p.targets)
        ]
