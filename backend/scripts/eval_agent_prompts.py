"""Bounded diagnostic prompt comparison; never creates a business run or writes to the KB."""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import re
import subprocess
import time
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from packages.agents.comparator.prompt_builder import build_comparator_prompt
from packages.agents.prompt_contract import EVIDENCE_RULES, prompt_trace_metadata
from packages.agents.writer.prompt_builder import (
    WriterPromptBuilder,
    writer_user_research_policy_text,
)
from packages.config import get_settings
from packages.llm.doubao_client import DoubaoClient
from packages.research.budget import research_depth_budget
from packages.schema.api_dto import RunDetail
from packages.schema.decision_brief import decision_brief_prompt_context
from packages.schema.models import AnalysisPlan

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "40e0f520b7923959c791fb197b741cfdff713200"


def _usable_url(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def score_output(case: dict, output: object) -> dict:
    """Mechanical checks only; these do not prove semantic report faithfulness."""
    allowed = set(case.get("allowed_source_ids", []))
    if case["role"] == "writer":
        text = output if isinstance(output, str) else ""
        ids = re.findall(r"\[source:([^\]#]+)(?:#chunk:\d+)?\]", text)
        return {
            "text_valid": bool(text.strip()),
            "citations_valid": bool(ids) and set(ids) <= allowed,
            "required_text_preserved": all(
                value in text for value in case.get("required_text", [])
            ),
            "required_headings_present": all(
                value in text for value in case.get("expected_headings", [])
            ),
            "chars": len(text),
        }
    payload = output if isinstance(output, dict) else {}
    if case["role"] == "collector":
        sources = payload.get("sources")
        sources = sources if isinstance(sources, list) else []
        action = payload.get("action")
        target_valid = (
            _usable_url(payload.get("url"))
            if action == "fetch_page"
            else isinstance(payload.get("query"), str) and bool(payload["query"].strip())
            if action == "web_search"
            else True
        )
        return {
            "json_valid": isinstance(output, dict),
            "correct_action": action in case["expected_actions"] and target_valid,
            "action_target_valid": target_valid,
            "candidate_urls_valid": all(
                isinstance(item, dict) and _usable_url(item.get("url")) for item in sources
            ),
        }
    dimension = case["dimension"]
    assessment_map = payload.get("assessments")
    assessment_map = assessment_map if isinstance(assessment_map, dict) else {}
    assessment = assessment_map.get(dimension)
    assessment = assessment if isinstance(assessment, dict) else {}
    winners = payload.get("winner_by_dimension")
    winners = winners if isinstance(winners, dict) else {}
    winner = assessment.get("winner", winners.get(dimension))
    winner = (
        None
        if not assessment
        and winner
        in (
            None,
            "",
            "tie",
            "not comparable",
            "not_comparable",
            "insufficient_evidence",
            "insufficient evidence",
        )
        else winner
    )
    ids = assessment.get("source_ids", [])
    citations_valid = (
        isinstance(ids, list) and all(isinstance(item, str) for item in ids) and set(ids) <= allowed
    )
    expected_winner = case.get("expected_winner")
    return {
        "json_valid": isinstance(output, dict),
        "correct_status": assessment.get("status") == case["expected_status"]
        if assessment
        else None,
        "no_unsupported_winner": winner is None and (not assessment or "winner" in assessment)
        if expected_winner is None
        else winner == expected_winner,
        "citations_valid": citations_valid,
        "required_evidence_cited": set(case.get("required_source_ids", [])) <= set(ids)
        if citations_valid
        else False,
    }


def _inline_prompt(source: str, method_name: str, values: dict) -> tuple[str, str, str]:
    tree = ast.parse(source)
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == method_name
    )
    call = next(
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"_trace_llm_json", "_trace_llm_text"}
    )
    fields = {}
    for kw in call.keywords:
        if kw.arg in {"system", "user", "schema_hint"}:
            fields[kw.arg] = eval(
                compile(ast.Expression(kw.value), "<fixed-repo-prompt>", "eval"),
                {"__builtins__": {}},
                values,
            )
    return fields["system"], fields["user"], fields.get("schema_hint", "")


def render_prompt(case: dict, variant: str, baseline_sources: dict) -> tuple[str, str, str]:
    detail = RunDetail(
        id="prompt-eval-fixed",
        topic=case["topic"],
        status="running",
        execution_mode="demo",
        created_at="2026-10-07T00:00:00",
        updated_at="2026-10-07T00:00:00",
        output_language="zh-CN",
        plan=AnalysisPlan(
            topic=case["topic"],
            competitors=case.get("competitors", ["A", "B"]),
            dimensions=[case.get("dimension", "pricing")],
            research_depth="quick",
            decision_brief=case.get("decision_brief"),
        ),
    )
    evidence_json = json.dumps(case["evidence"], ensure_ascii=False)
    values = dict(
        detail=detail,
        analysis_json=evidence_json,
        evidence_json=evidence_json,
        decision_brief_prompt_context=decision_brief_prompt_context,
        json=json,
        EVIDENCE_RULES=EVIDENCE_RULES,
    )
    if case["role"] == "comparator":
        if variant == "candidate":
            prompt = build_comparator_prompt(
                detail, analysis_json=evidence_json, evidence_json=evidence_json
            )
            return prompt.system, prompt.user, prompt.schema_hint
        return _inline_prompt(
            baseline_sources["comparator"], "_comparator_payload_with_retries", values
        )
    if case["role"] == "collector":
        values.update(
            competitor=case.get("competitors", ["A"])[0],
            dimension=case.get("dimension", "pricing"),
            skill=SimpleNamespace(
                description="Find current source-backed product prices and their conditions."
            ),
            allowed_actions=["web_search", "robots_check", "fetch_page", "finish"],
            qa_feedback=[],
            observations=case["evidence"]["observations"],
            coverage_feedback=case["evidence"]["coverage"],
            turn=1,
            max_turns=3,
        )
        source = (
            baseline_sources["collector"]
            if variant == "baseline"
            else (ROOT / "backend/packages/agents/collectors/logic.py").read_text()
        )
        return _inline_prompt(source, "_run_collector_competitor_react", values)
    kwargs = dict(
        language_guidance="Use Simplified Chinese headings and prose; keep source IDs unchanged.",
        user_research_policy=writer_user_research_policy_text(),
        memory_context="none",
        layer_context="L1",
        grounding_prompt=(
            "Grounded Evidence Contract: use only allowed_source_ids and supplied facts."
        ),
        community_policy_text="Community observations do not establish official commitments.",
        writer_context_json=evidence_json,
        required_sections="## 一句话结论\n## 产品对比\n## 证据与局限",
    )
    if variant == "candidate":
        prompt = WriterPromptBuilder().first_draft_prompt(detail, **kwargs)
        return prompt.system, prompt.user, ""
    values.update(kwargs)
    values.update(
        self=SimpleNamespace(_writer_community_policy_text=lambda: kwargs["community_policy_text"]),
        report_chars=research_depth_budget("quick").report_chars,
        allocation_instruction=(
            "Focus on the core summary, product comparison, evidence and limitations. "
        ),
        core_depth_instruction=(
            "Summarize the target product, core competitor comparison, evidence, "
            "limitations and next validation step concisely. "
        ),
        layer_instruction=(
            "For quick research, use only the requested compact sections and disclose limitations."
        ),
    )
    return _inline_prompt(
        baseline_sources["writer"], "_writer_markdown_report_from_evidence_pack", values
    )


def load_baseline(ref: str) -> dict:
    return {
        role: subprocess.check_output(
            ["git", "show", f"{ref}:backend/packages/agents/{directory}/logic.py"],
            cwd=ROOT,
            text=True,
        )
        for role, directory in [
            ("writer", "writer"),
            ("comparator", "comparator"),
            ("collector", "collectors"),
        ]
    }


async def evaluate(args) -> dict:
    cases = [json.loads(line) for line in args.cases.read_text().splitlines() if line.strip()]
    if not 1 <= len(cases) <= 12:
        raise ValueError(
            "Diagnostic evaluation accepts 1-12 fixed cases (at most 24 provider calls)."
        )
    baseline_sources = load_baseline(args.baseline)
    prepared = [
        (case, variant, render_prompt(case, variant, baseline_sources))
        for case in cases
        for variant in ("baseline", "candidate")
    ]
    report = dict(
        baseline_commit=args.baseline,
        mode="live" if args.live else "render_only",
        dataset_sha256=hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        limitations=[
            "Fixed synthetic diagnostic cases; not a held-out real research benchmark.",
            "Comparator schema and Collector coverage feedback change along with prompt wording.",
            "Mechanical checks do not measure full-report faithfulness or live retrieval.",
        ],
        results=[],
    )
    client = None
    if args.live:
        settings = get_settings()
        if settings.llm_provider_name != "deepseek" or not settings.ark_api_key:
            raise ValueError(
                "A configured primary DeepSeek provider is required; "
                "credentials are never exported."
            )
        settings = replace(
            settings,
            backup_llm_api_key=None,
            backup_llm_model=None,
            llm_temperature=0,
            llm_max_retries=0,
            llm_max_output_tokens=1400,
            llm_timeout_seconds=45,
        )
        client = DoubaoClient(settings)
        report["model"] = settings.ark_model
        report["temperature"] = 0
        report["max_output_tokens"] = 1400
    for case, variant, (system, user, schema) in prepared:
        row = dict(
            case_id=case["id"],
            role=case["role"],
            variant=variant,
            **prompt_trace_metadata(
                case["role"], f"eval_{case['role']}", system, user, schema or None
            ),
        )
        row["prompt_chars"] = len(system) + len(user) + len(schema)
        if client:
            started = time.perf_counter()
            try:
                output = (
                    await client.complete_json(system=system, user=user, schema_hint=schema)
                    if schema
                    else await client.complete_text(system=system, user=user)
                )
                row.update(output=output, scores=score_output(case, output), status="ok")
            except Exception as exc:
                # Store only error type; provider messages can contain request/response data.
                row.update(status="error", error_type=type(exc).__name__)
            usage = client.consume_last_usage()
            row["usage"] = asdict(usage) if usage else None
            row["duration_ms"] = round((time.perf_counter() - started) * 1000)
        report["results"].append(row)
        # Checkpoint after each bounded call; no credentials or real task context included.
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(
            json.dumps(
                {key: row[key] for key in ["case_id", "role", "variant", "status"] if key in row}
            ),
            flush=True,
        )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "eval/agent-prompt-contract-v1.jsonl")
    parser.add_argument("--baseline", default=BASELINE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--live", action="store_true", help="Opt in to at most 24 fixed-data DeepSeek calls."
    )
    args = parser.parse_args()
    asyncio.run(evaluate(args))


if __name__ == "__main__":
    main()
