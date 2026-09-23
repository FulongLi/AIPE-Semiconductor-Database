from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from aipe_devices.domain.base import Model
from aipe_devices.domain.provenance import AccessMetadata

from .plans import TestPlanItem


class MeasurementRequest(Model):
    schema_version: Literal["3.0.0"] = "3.0.0"
    id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    physical_sample_id: str | None = None
    test_plan_items: tuple[TestPlanItem, ...] = Field(min_length=1)
    access: AccessMetadata = AccessMetadata()

    @model_validator(mode="before")
    @classmethod
    def migrate_phase1(cls, value):
        if isinstance(value, dict) and "protocols" in value and "test_plan_items" not in value:
            value = dict(value)
            protocols = value.pop("protocols")
            conditions = value.pop("conditions", ())
            metrics = value.pop("requested_metrics", ())
            repetitions = value.pop("repetitions", 1)
            # Preserve the legacy meaning only during migration.
            value["test_plan_items"] = [
                dict(
                    id=f"legacy-{p}-{c}",
                    protocol=protocol,
                    fixed_conditions=condition,
                    requested_metrics=metrics,
                    repetitions=repetitions,
                )
                for p, protocol in enumerate(protocols)
                for c, condition in enumerate(conditions)
            ]
        return value

    @model_validator(mode="after")
    def unique_items(self):
        if len({i.id for i in self.test_plan_items}) != len(self.test_plan_items):
            raise ValueError("Test-plan item IDs must be unique")
        return self

    def model_copy(self, *, update=None, deep=False):
        # Compatibility for Phase-1 callers changing the global repetition count.
        update = dict(update or {})
        if "repetitions" in update:
            count = update.pop("repetitions")
            update["test_plan_items"] = tuple(
                TestPlanItem.model_validate({**i.model_dump(), "repetitions": count})
                for i in update.get("test_plan_items", self.test_plan_items)
            )
        return super().model_copy(update=update, deep=deep)


def generate_request(*, device_id, test_plan_items=None, **kwargs):
    values = dict(id=str(uuid4()), device_id=device_id, **kwargs)
    if test_plan_items is not None:
        values["test_plan_items"] = tuple(test_plan_items)
    return MeasurementRequest.model_validate(values)
