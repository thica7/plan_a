from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StructuredSectionGenerationError(RuntimeError):
    section_key: str
    section_id: str
    schema_name: str
    message: str
    error_kind: str = "validation"
    attempt: str = "retry"

    def __str__(self) -> str:
        return (
            f"{self.section_key} ({self.schema_name}) failed structured generation "
            f"during {self.attempt} with {self.error_kind}: {self.message}"
        )


@dataclass(frozen=True)
class StructuredReportGenerationError(RuntimeError):
    failed_sections: tuple[StructuredSectionGenerationError, ...]

    def __str__(self) -> str:
        section_names = ", ".join(error.section_key for error in self.failed_sections)
        return f"structured report generation failed for section(s): {section_names}"
