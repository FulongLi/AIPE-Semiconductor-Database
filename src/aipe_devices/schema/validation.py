from typing import Literal

from aipe_devices.domain.base import Model


class ValidationIssue(Model):
    severity: Literal["error", "warning"]
    code: str
    path: str
    message: str


class ValidationReport(Model):
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def raise_for_errors(self) -> None:
        if not self.valid:
            raise ValueError(
                "; ".join(f"{i.path}: {i.message}" for i in self.issues if i.severity == "error")
            )
