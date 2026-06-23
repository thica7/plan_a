from __future__ import annotations

from dataclasses import dataclass

from packages.business_intel.release_gate import REPORT_RICHNESS_MINIMUMS
from packages.business_intel.report_quality import compare_run_quality
from packages.schema.api_dto import RunDetail


@dataclass(frozen=True)
class WriterQualityGate:
    def assemble_repair_gate(
        self,
        detail: RunDetail,
        markdown: str,
    ) -> dict[str, object]:
        candidate = detail.model_copy(update={"report_md": markdown})
        comparison = compare_run_quality(candidate)
        metric_by_name = {
            metric.name: metric.target_value for metric in comparison.metrics
        }
        quality_gate_metrics = {
            name: float(metric_by_name.get(name) or 0.0)
            for name in REPORT_RICHNESS_MINIMUMS
        }
        reasons = [
            name
            for name, minimum in REPORT_RICHNESS_MINIMUMS.items()
            if quality_gate_metrics[name] < minimum
        ]
        return {
            "quality_gate_passed": not reasons,
            "quality_gate_reasons": reasons,
            "quality_gate_metrics": quality_gate_metrics,
            **quality_gate_metrics,
        }
