"""Document integrity report.

The integrity stage collects **all** findings (it never fails fast) so the frontend
can present every issue at once, before the user commits to extraction. BLOCKER
findings gate extraction; WARNING annotates pages and lowers their confidence.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import Severity


class IntegrityFinding(BaseModel):
    check_id: str
    severity: Severity
    message: str
    page_index: int | None = None
    detail: dict = Field(default_factory=dict)


class IntegrityReport(BaseModel):
    schema_version: int = 1
    is_encrypted: bool = False
    is_password_protected: bool = False
    is_corrupt: bool = False
    has_text_layer: bool = True
    page_count: int = 0
    scanned_page_ratio: float = 0.0
    findings: list[IntegrityFinding] = Field(default_factory=list)

    def add(self, finding: IntegrityFinding) -> None:
        self.findings.append(finding)

    @property
    def has_blockers(self) -> bool:
        return any(f.severity == Severity.BLOCKER for f in self.findings)

    def by_severity(self, severity: Severity) -> list[IntegrityFinding]:
        return [f for f in self.findings if f.severity == severity]
