from __future__ import annotations

from packages.research.models import RepairTask
from packages.schema.models import RedoScope


def repair_tasks_to_redo_scopes(tasks: list[RepairTask]) -> list[RedoScope]:
    return _dedupe([repair_task_to_redo_scope(task) for task in tasks])


def repair_task_to_redo_scope(task: RepairTask) -> RedoScope:
    kind = _redo_kind(task)
    dimension = task.dimension if task.dimension not in {"general", "report"} else None
    competitor = task.competitor
    return RedoScope(
        kind=kind,  # type: ignore[arg-type]
        target_subagent=dimension,
        target_competitor=competitor,
        target_competitors=[competitor] if competitor else [],
        rationale=_rationale(task),
    )


def _redo_kind(task: RepairTask) -> str:
    if task.strategy in {
        "targeted_discovery",
        "pricing_model_repair",
        "feature_slot_repair",
        "persona_schema_repair",
    }:
        return "collector"
    if task.strategy == "mark_not_applicable":
        return "analyst"
    return "writer_only"


def _rationale(task: RepairTask) -> str:
    action = f" action={task.required_action}."
    fields = f" fields={', '.join(task.target_fields)}." if task.target_fields else ""
    claim_ids = _metadata_list(task, "claim_ids")
    evidence_ids = _metadata_list(task, "evidence_ids")
    claims = f" claim_ids={', '.join(claim_ids[:3])}." if claim_ids else ""
    evidence = f" evidence_ids={', '.join(evidence_ids[:3])}." if evidence_ids else ""
    query_hints = f" query_hints={'; '.join(task.query_hints[:3])}." if task.query_hints else ""
    return f"{task.acceptance_rule}{action}{fields}{claims}{evidence}{query_hints}".strip()


def _metadata_list(task: RepairTask, key: str) -> list[str]:
    value = task.metadata.get(key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def _dedupe(scopes: list[RedoScope]) -> list[RedoScope]:
    result: list[RedoScope] = []
    seen: set[tuple[str, str | None, str | None, tuple[str, ...]]] = set()
    for scope in scopes:
        key = (
            scope.kind,
            scope.target_subagent,
            scope.target_competitor,
            tuple(scope.target_competitors),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(scope)
    return result
