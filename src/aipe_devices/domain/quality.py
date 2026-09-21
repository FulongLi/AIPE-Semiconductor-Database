from pydantic import Field, model_validator

from .base import Model


class Uncertainty(Model):
    """Absolute uncertainty uses the same unit as its associated value."""

    standard: float | None = Field(default=None, ge=0)
    repetitions: int | None = Field(default=None, ge=1)
    minimum: float | None = None
    maximum: float | None = None
    confidence_interval: tuple[float, float] | None = None
    confidence_level: float | None = Field(default=None, gt=0, lt=1)
    sample_variation: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def ordered_bounds(self):
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Uncertainty minimum must not exceed maximum")
        if self.confidence_interval and self.confidence_interval[0] > self.confidence_interval[1]:
            raise ValueError("Confidence interval bounds must be ordered")
        return self


class Quality(Model):
    flags: tuple[str, ...] = ()
    review_status: str = "unreviewed"
