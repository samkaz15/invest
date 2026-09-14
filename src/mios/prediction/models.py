"""What a forecast is.

The shape exists to make a stored forecast replayable: given the row, a
reader can recompute the number. A forecast whose arithmetic cannot be
reconstructed from its own record is the untraceable score this project
deleted from BIOS (docs/REPOSITORY_AUDIT.md §8 U-12), and adding one back
under a new name would be the same mistake.
"""

from datetime import date, datetime

from pydantic import Field, field_validator

from mios.common.errors import MiosError
from mios.common.ids import IdKind, pydantic_id_validator
from mios.common.schema import MiosModel, MiosRecord
from mios.common.timeutil import ensure_utc


class Driver(MiosModel):
    """One input's contribution to a forecast.

    ``contribution`` is in the target's units and is literally what was
    added to the baseline, so the drivers of a forecast sum to the
    adjustment. ``rationale`` says why in a sentence a human can check.
    """

    series_id: str
    label: str
    value: float | None  # the driver's reading, in its own units
    weight: float
    contribution: float  # weight applied, in the target's units
    rationale: str

    @property
    def direction(self) -> int:
        if self.contribution > 0:
            return 1
        return -1 if self.contribution < 0 else 0


class Forecast(MiosRecord):
    """One prediction, made at one moment, from one data cutoff."""

    forecast_id: str
    target_series_id: str
    target_period: date
    predicted_at: datetime
    as_of: datetime

    point_value: float | None
    baseline_value: float | None
    upside_prob: float | None = Field(default=None, ge=0, le=1)
    downside_prob: float | None = Field(default=None, ge=0, le=1)
    confidence: float = Field(ge=0, le=1)

    method_version: str
    drivers: list[Driver] = Field(default_factory=list)
    #: Drivers pointing against the net call. Surfaced rather than averaged
    #: away: disagreement among inputs is information about how much to
    #: trust the number, and a mean destroys it.
    contradictions: list[str] = Field(default_factory=list)
    #: Inputs that were missing, named. A forecast built on half its inputs
    #: must say so on its face (CONSTITUTION.md Art.4-4).
    data_gaps: list[str] = Field(default_factory=list)

    @field_validator("forecast_id")
    @classmethod
    def _fid(cls, v: str) -> str:
        return pydantic_id_validator(v, IdKind.FORECAST)

    @field_validator("target_series_id")
    @classmethod
    def _sid(cls, v: str) -> str:
        return pydantic_id_validator(v, IdKind.SERIES)

    @field_validator("predicted_at", "as_of")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        try:
            return ensure_utc(v)
        except MiosError as exc:
            raise ValueError(str(exc)) from exc

    @property
    def adjustment(self) -> float | None:
        """How far the drivers moved the call away from the naive answer.

        The honest measure of whether the model is doing anything: if this
        is always near zero, the drivers are decoration.
        """
        if self.point_value is None or self.baseline_value is None:
            return None
        return self.point_value - self.baseline_value
