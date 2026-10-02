"""Export bounded, redacted Agent evaluation trajectories from existing SQLite journals."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import unquote

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from packages.compliance import redact_text  # noqa: E402

MAX_TEXT = 600
MAX_ACTIONS = 100
MAX_FEEDBACK = 50
MAX_SCOPE_ITEMS = 20
USAGE_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
)
BRIEF_FIELDS = ("decision_question", "primary_job", "success_metric")
SPLIT_POLICY = {
    "algorithm": "sha256_task_group_v1",
    "ratios": {"train": 70, "validation": 15, "holdout": 15},
    "identity_fields": ["workspace_id", "topic", "target_product.name", "decision_brief"],
}
# Compliance covers known key families. Also remove unrecognizable credentials
# in errors/URLs (e.g. api_key=short), before any preview truncation.
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:[\w-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret"
    r"|authorization)|token|key)[\"']?\s*[:=]\s*(?:(?:bearer|basic)\s+)?"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[^\s,;&]+")
_URL_CREDENTIALS = re.compile(r"(?i)(https?://)[^/\s?#]+@")
_CREDENTIAL_FRAGMENT = re.compile(
    r"(?i)\b(?:sk-|pplx-|gsk_|xai-|AIza|AKIA|"
    r"(?:ak|rk|pk|xoxb|ghp|github_pat|hf|glpat)_)[A-Za-z0-9_-]+"
)


class ExportError(ValueError):
    """A safe, fixed diagnostic that never includes a raw record or exception."""


def _redact(value: str) -> str:
    # Decode escaped URL credentials before applying the same redaction rules.
    text = value
    while (decoded := unquote(text)) != text:
        text = decoded
    text = _URL_CREDENTIALS.sub(r"\1[redacted:credentials]@", text)
    text = _SECRET_ASSIGNMENT.sub("[redacted:secret]", text)
    text = _BEARER.sub("[redacted:bearer_token]", text)
    return redact_text(text).text


def _text(value: Any) -> str | None:
    return _redact(value)[:MAX_TEXT] if isinstance(value, str) else None


def _number(value: Any, *, integer: bool = False) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if integer and not isinstance(value, int):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 2**63 - 1 else None
    return value if math.isfinite(value) and value >= 0 else None


def _summary(span: dict[str, Any], direction: str) -> tuple[str | None, str | None, str | None]:
    complete = span.get(f"full_{direction}")
    if isinstance(complete, str) and complete:
        # Legacy producers truncated previews before redaction. The complete text
        # is used only to build a redacted bounded excerpt, never exported as a field.
        return _text(complete), "full_text", None
    preview = span.get(f"{direction}_preview")
    if not isinstance(preview, str) or not preview:
        return None, None, "missing_text"
    original_chars = _number(span.get(f"{direction}_chars"), integer=True)
    if preview.rstrip().endswith(("...", "…")) or (
        original_chars is not None and original_chars > len(preview)
    ):
        return None, None, "truncated_preview"
    safe = _redact(preview)
    if _CREDENTIAL_FRAGMENT.search(safe) or "@" in safe:
        return None, None, "unsafe_preview"
    return safe[:MAX_TEXT], "preview", None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _non_real(record: dict[str, Any]) -> bool:
    for values in (record, _mapping(record.get("metadata"))):
        if "execution_mode" in values and values["execution_mode"] != "real":
            return True
        for key, value in values.items():
            name = str(key).lower().replace("_", "").replace("-", "")
            if name in {
                "demo",
                "isdemo",
                "demomode",
                "simulated",
                "issimulated",
                "simulation",
                "surveysimulated",
                "synthetic",
                "fixtureonly",
                "providerdemo",
            }:
                if (
                    value is True
                    or value == 1
                    or str(value).strip().lower()
                    in {
                        "true",
                        "yes",
                        "1",
                        "on",
                        "demo",
                        "simulated",
                        "simulation",
                    }
                ):
                    return True
            if name in {"mode", "provider", "llmprovider", "providername"}:
                if isinstance(value, str) and value.strip().lower().startswith(("demo", "simulat")):
                    return True
            if name in {"sourcetype", "sourcerole", "communitysourcetype"}:
                if isinstance(value, str) and any(
                    part in {"demo", "simulated", "simulation", "synthetic"}
                    for part in re.split(r"[_\s-]+", value.strip().lower())
                ):
                    return True
    return False


def _read_records(path: Path, table: str, workspace: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ExportError("Source database does not exist or is not a file.")
    json_column = {"runs": "detail_json", "memory_feedback": "record_json"}[table]
    try:
        # Never instantiate stores: their constructors can create/migrate databases.
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            rows = conn.execute(
                f"SELECT id, workspace_id, project_id, {json_column} FROM {table} "
                "WHERE workspace_id = ? ORDER BY id",
                (workspace,),
            ).fetchall()
    except sqlite3.Error as exc:
        raise ExportError("Unable to read source SQLite database or required schema.") from exc
    records = []
    for row_id, row_workspace, row_project, raw in rows:
        try:
            record = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ExportError("Invalid JSON in source database.") from exc
        if not isinstance(record, dict):
            raise ExportError("Source record must be a JSON object.")
        # SQL summary columns alone are insufficient for tenancy and association.
        if (
            record.get("id") == row_id
            and isinstance(row_id, str)
            and row_id
            and record.get("workspace_id") == row_workspace == workspace
            and record.get("project_id") == row_project
        ):
            records.append(record)
    return records


def _plan(record: dict[str, Any]) -> dict[str, Any]:
    plan = record.get("plan")
    if not isinstance(plan, dict) or not isinstance(plan.get("topic"), str):
        raise ExportError("Explicit real run has an invalid task scope.")
    return plan


def task_group(record: dict[str, Any], workspace: str) -> tuple[str, str]:
    """Group reruns before splitting; depth/candidates/time/run ID do not enter identity."""
    plan = _plan(record)
    target = _mapping(plan.get("target_product"))
    brief = _mapping(plan.get("decision_brief"))

    def normalize(value: Any) -> str:
        return " ".join(_redact(value).casefold().split()) if isinstance(value, str) else ""

    identity = {
        "workspace_id": normalize(workspace),
        "topic": normalize(plan["topic"]),
        "target_product_name": normalize(target.get("name")),
        "decision_brief": {key: normalize(brief.get(key)) for key in BRIEF_FIELDS},
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    bucket = int(digest, 16) % 100
    return digest, "train" if bucket < 70 else "validation" if bucket < 85 else "holdout"


def _scope(record: dict[str, Any]) -> dict[str, Any]:
    plan = _plan(record)
    target = _mapping(plan.get("target_product"))
    brief = _mapping(plan.get("decision_brief"))
    scope: dict[str, Any] = {
        "topic": _text(plan["topic"]),
        "target_product": {
            key: _text(target.get(key))
            for key in ("name", "official_url", "category", "audience", "market")
        }
        if target
        else None,
        "research_depth": _text(plan.get("research_depth")),
        "decision_brief": {key: _text(brief.get(key)) for key in BRIEF_FIELDS},
    }
    for key in ("competitors", "dimensions"):
        values = plan.get(key, [])
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise ExportError("Explicit real run has an invalid task scope list.")
        scope[key] = [_text(value) for value in values[:MAX_SCOPE_ITEMS]]
        scope[key + "_omitted"] = max(0, len(values) - MAX_SCOPE_ITEMS)
    return scope


def _action(span: dict[str, Any]) -> dict[str, Any]:
    metadata = _mapping(span.get("metadata"))
    usage = {key: _number(metadata.get(key), integer=True) for key in USAGE_FIELDS}
    source = metadata.get("token_usage_source")
    provider_usage = source in (None, "provider") and any(
        value is not None for value in usage.values()
    )
    if not provider_usage:
        usage = dict.fromkeys(USAGE_FIELDS)
    action = {key: _text(span.get(key)) for key in ("id", "kind", "agent", "name", "status")}
    for direction in ("input", "output"):
        summary, source, reason = _summary(span, direction)
        action[f"{direction}_summary"] = summary
        action[f"{direction}_summary_source"] = source
        action[f"{direction}_summary_omitted_reason"] = reason
    action.update(
        {
            "duration_ms": _number(span.get("duration_ms")),
            "provider": _text(span.get("provider") or metadata.get("llm_provider")),
            "model": _text(span.get("model") or metadata.get("llm_model")),
            "usage_source": "provider" if provider_usage else "estimate",
            "provider_usage": usage,
            "provider_usage_scope": "last_attempt_only",
            "token_estimates": {
                key: _number(span.get(key), integer=True)
                for key in ("input_tokens_estimate", "output_tokens_estimate")
            },
            "attempts": _number(metadata.get("llm_request_attempts"), integer=True),
            "budget_charge": {
                "tokens": _number(metadata.get("llm_tokens_charged"), integer=True),
                "cost_usd": _number(metadata.get("llm_cost_charged_usd")),
                "basis": "conservative_budget",
            },
            "cost_estimate_usd": _number(span.get("cost_estimate_usd")),
            "price_basis": _text(metadata.get("price_basis")),
        }
    )
    return action


def _feedback(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _text(record.get(key))
        for key in ("id", "feedback_type", "target_type", "report_version_id", "message")
    } | {"source": _text(_mapping(record.get("metadata")).get("source"))}


def export_agent_eval(
    journal: Path,
    workspace: str,
    *,
    feedback_db: Path | None = None,
) -> dict[str, Any]:
    """Read raw JSON without model defaults or migrations; correctness remains unlabelled."""
    if not workspace.strip():
        raise ExportError("Workspace must be nonempty.")
    runs = _read_records(Path(journal), "runs", workspace)
    feedback = _read_records(Path(feedback_db), "memory_feedback", workspace) if feedback_db else []
    tasks = []
    for record in runs:
        if record.get("execution_mode") != "real" or _non_real(record):
            continue
        spans = record.get("trace_spans", [])
        if not isinstance(spans, list) or any(not isinstance(span, dict) for span in spans):
            raise ExportError("Explicit real run has invalid trace spans.")
        eligible = [span for span in spans if not _non_real(span)]
        linked = [
            item
            for item in feedback
            if item.get("run_id") == record["id"]
            and item.get("project_id") == record.get("project_id")
        ]
        group_id, split = task_group(record, workspace)
        checkpoint = _mapping(record.get("llm_budget_checkpoint"))
        tasks.append(
            {
                "run_id": _text(record["id"]),
                "project_id": _text(record.get("project_id")),
                "execution_mode": "real",
                "task_group_id": group_id,
                "split": split,
                "scope": _scope(record),
                "actions": [_action(span) for span in eligible[:MAX_ACTIONS]],
                "actions_omitted": max(0, len(eligible) - MAX_ACTIONS),
                "actions_filtered": len(spans) - len(eligible),
                "feedback": [_feedback(item) for item in linked[:MAX_FEEDBACK]],
                "feedback_omitted": max(0, len(linked) - MAX_FEEDBACK),
                "result": {"status": _text(record.get("status"))},
                "reward": {"correctness": None, "source": None},
                "budget_checkpoint": {
                    "calls": _number(checkpoint.get("calls"), integer=True),
                    "repairs": _number(checkpoint.get("repairs"), integer=True),
                    "tokens_charged": _number(checkpoint.get("tokens_charged"), integer=True),
                    "cost_charged_usd": _number(checkpoint.get("cost_charged_usd")),
                    "basis": "conservative_budget_including_pending_reservations",
                },
            }
        )
    return {
        "schema_version": 1,
        "dataset_kind": "journal_explicit_real",
        "workspace_id": _text(workspace),
        "split_policy": SPLIT_POLICY,
        "limits": {
            "text_chars": MAX_TEXT,
            "actions_per_run": MAX_ACTIONS,
            "feedback_per_run": MAX_FEEDBACK,
            "scope_items": MAX_SCOPE_ITEMS,
        },
        "tasks": tasks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only SQLite export of explicit real Agent runs, with redacted summaries.",
        epilog="All correctness rewards remain null. Usage is the last attempt only; budget "
        "charges and configured cost estimates are not account invoices. Synthetic "
        "split examples and commands: backend/tests/fixtures/agent_eval/README.md",
    )
    parser.add_argument(
        "--journal", required=True, type=Path, help="Existing RunJournal SQLite file"
    )
    parser.add_argument("--workspace", required=True, help="Exact workspace ID to export")
    parser.add_argument("--output", required=True, type=Path, help="JSON output path")
    parser.add_argument(
        "--feedback-db", type=Path, help="Optional existing preference-memory SQLite"
    )
    args = parser.parse_args()
    try:
        for source in (args.journal, args.feedback_db):
            if source is not None and (
                args.output.resolve() == source.resolve()
                or (args.output.exists() and source.exists() and args.output.samefile(source))
            ):
                raise ExportError("Output must not overwrite a source database.")
        result = export_agent_eval(args.journal, args.workspace, feedback_db=args.feedback_db)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )
    except ExportError as exc:
        print(f"Agent eval export failed: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("Agent eval export failed: Unable to access input or output file.", file=sys.stderr)
        return 1
    print(f"Exported {len(result['tasks'])} runs; correctness rewards are unlabelled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
