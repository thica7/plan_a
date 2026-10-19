from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "backend/scripts/eval_evidence_binding.py"
CASES = ROOT / "eval/product-condition-review-v1.jsonl"
CANDIDATES = ROOT / "eval/archive/product-condition-review-v1-candidate/cases.jsonl"


def runner():
    assert SCRIPT.is_file(), "evidence binding diagnostic runner is missing"
    return importlib.import_module("scripts.eval_evidence_binding")


def cases():
    return [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]


def test_default_lists_without_loading_settings_or_calling_model(monkeypatch, capsys):
    module = runner()
    monkeypatch.setattr(module, "get_settings", lambda: pytest.fail("settings loaded"))
    monkeypatch.setattr(module, "run_diagnostic", lambda *a, **k: pytest.fail("model path called"))
    asyncio.run(module.main([]))
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "list_only"
    assert result["case_ids"] == [f"condition-v1-{i:03}" for i in (1, 2, 4, 5)]
    assert result["input_sha256"] == hashlib.sha256(CASES.read_bytes()).hexdigest()
    assert result["collector_status"] == "skipped"
    assert result["llm_transport_attempts"] == 0


def test_formal_rejects_all_candidate_rows_even_with_product_selection():
    with pytest.raises(ValueError, match="human review"):
        runner().load_cases(CANDIDATES, mode="formal")


def test_human_reviewed_input_passes_formal_preview_without_model(monkeypatch, capsys):
    module = runner()
    monkeypatch.setattr(module, "get_settings", lambda: pytest.fail("settings loaded"))
    monkeypatch.setattr(module, "run_diagnostic", lambda *a, **k: pytest.fail("model called"))
    asyncio.run(module.main(["--mode", "formal"]))
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "list_only" and result["review_mode"] == "formal"
    assert result["llm_transport_attempts"] == 0


def test_review_promotion_preserves_reference_content_and_model_payload():
    module = runner()
    record = json.loads((ROOT / "eval/product-condition-review-v1-review.json").read_text())
    assert hashlib.sha256(CANDIDATES.read_bytes()).hexdigest() == record["candidate_sha256"]
    assert hashlib.sha256(CASES.read_bytes()).hexdigest() == record["reviewed_dataset_sha256"]
    previous = module.load_cases(CANDIDATES)
    reviewed = module.load_cases(CASES, mode="formal")
    review_fields = {"review_status", "reviewed_by", "reviewed_at"}
    for before, after in zip(previous, reviewed, strict=True):
        assert {k: v for k, v in before.items() if k not in review_fields} == {
            k: v for k, v in after.items() if k not in review_fields
        }
        assert after["reviewed_by"] == "project_user"
        assert after["reviewed_at"] == record["review_recorded_at"]
        assert module.allowed_payload(before) == module.allowed_payload(after)


def test_formal_requires_every_row_reviewer_and_time(tmp_path):
    rows = cases()
    for row in rows:
        row.update(
            review_status="reviewed",
            reviewed_by="human-reviewer",
            reviewed_at="2026-10-16T12:00:00Z",
        )
    path = tmp_path / "reviewed.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows))
    assert len(runner().load_cases(path, mode="formal")) == 8
    rows[-1]["reviewed_by"] = None
    path.write_text("\n".join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError, match="human review"):
        runner().load_cases(path, mode="formal")


def test_allowed_payload_strips_gold_and_review_fields_recursively():
    row = deepcopy(cases()[0])
    for field in (
        "reference_answer",
        "expected_outcome",
        "required_conditions",
        "forbidden_inferences",
        "review_status",
        "reviewed_by",
        "reviewed_at",
    ):
        row[field] = "DO_NOT_SEND_" + field
        row["sources"][0][field] = "DO_NOT_SEND_" + field
    payload = runner().allowed_payload(row)
    assert set(payload) == {"id", "product", "question", "sources"}
    assert "DO_NOT_SEND" not in json.dumps(payload)
    assert payload["sources"][0]["excerpt"] == row["sources"][0]["excerpt"]


def test_source_drift_aborts_before_live_entry(monkeypatch, tmp_path):
    module = runner()
    path = tmp_path / "cases.jsonl"
    path.write_bytes(CASES.read_bytes())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    rows = cases()
    rows[0]["sources"][0]["excerpt"] += " changed"
    path.write_text("\n".join(json.dumps(row) for row in rows))
    monkeypatch.setattr(module, "get_settings", lambda: pytest.fail("drift reached settings"))
    with pytest.raises(ValueError, match="drift"):
        asyncio.run(
            module.main(["--cases", str(path), "--live", "--expected-input-sha256", digest])
        )


def test_manifest_rejects_drift_after_cases_are_loaded(monkeypatch, tmp_path):
    module = runner()
    path = tmp_path / "cases.jsonl"
    path.write_bytes(CASES.read_bytes())
    frozen_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    real_load = module.load_cases

    def changed_after_load(*args, **kwargs):
        rows = real_load(*args, **kwargs)
        path.write_bytes(path.read_bytes() + b"\n")
        return rows

    monkeypatch.setattr(module, "load_cases", changed_after_load)
    monkeypatch.setattr(module, "run_diagnostic", lambda *a, **k: pytest.fail("drift reached live"))
    with pytest.raises(ValueError, match="drift"):
        asyncio.run(
            module.main(["--cases", str(path), "--live", "--expected-input-sha256", frozen_hash])
        )


def test_excerpt_mapping_is_verbatim_without_semantic_labels():
    module = runner()
    payload = module.allowed_payload(cases()[0])
    mapped = module.map_excerpt(payload, payload["sources"][0])
    module.validate_mapping(mapped)
    row = mapped["raw_source"].metadata["normalized_fields"][0]
    quote = payload["sources"][0]["excerpt"]
    assert row["evidence_terms"] == [quote] and row["evidence_quote"] == quote
    assert set(row) == {
        "kind",
        "slot",
        "competitor",
        "dimension",
        "evidence_terms",
        "evidence_quote",
        "evidence_item_ids",
        "source_url",
    }
    assert mapped["raw_source"].source_type == "manual_note"
    assert mapped["capture"].source_material_level == "unknown"
    assert mapped["raw_source"].metadata["input_mode"] == "fixed_official_excerpt"
    assert mapped["extraction"].quotes[0].start_offset == 0
    assert mapped["extraction"].quotes[0].end_offset == len(quote)
    assert all(item.status == "accepted" for item in mapped["items"])


def test_production_rejected_excerpt_retains_reason_and_cannot_mint_facts():
    module = runner()
    payload = module.allowed_payload(cases()[5])
    mapped = module.map_excerpt(payload, payload["sources"][0])
    assert mapped["items"][0].status == "rejected"
    assert "quote_missing_dimension_signal" in mapped["items"][0].rejection_reason
    assert mapped["raw_source"].metadata["normalized_fields"] == []


def test_changed_normalized_terms_are_rejected():
    module = runner()
    payload = module.allowed_payload(cases()[0])
    mapped = module.map_excerpt(payload, payload["sources"][0])
    mapped["raw_source"].metadata["normalized_fields"][0]["evidence_terms"] = [
        "fabricated semantic condition"
    ]
    with pytest.raises(ValueError, match="binding"):
        module.validate_mapping(mapped)


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("capture", "text", "changed original"),
        ("capture", "final_url", "https://example.com/other"),
        ("candidate", "competitor", "Other product"),
        ("extraction", "captured_page_id", "unrelated-capture"),
        ("raw_source", "competitor", "Other product"),
    ],
)
def test_quote_data_and_identity_tampering_is_rejected(target, field, value):
    module = runner()
    payload = module.allowed_payload(cases()[0])
    mapped = module.map_excerpt(payload, payload["sources"][0])
    setattr(mapped[target], field, value)
    with pytest.raises(ValueError, match="binding"):
        module.validate_mapping(mapped)


def test_reviewed_identity_does_not_promote_fixed_excerpt_to_a_capture():
    module = runner()
    for row in cases():
        payload = module.allowed_payload(row)
        mapped = module.map_excerpt(payload, payload["sources"][0])
        preflight = module.collector_preflight(mapped)
        assert preflight["identity_resolved"] is True
        assert preflight["semantic_page_allowed"] is False
        assert preflight["collector_status"] == "skipped"
        assert preflight["collector_llm_transport_attempts"] == 0
        assert preflight["blocker"] == "collector_not_executed"


def test_live_runner_reuses_native_trace_binding_writer_review_and_qa():
    module = runner()
    from packages.agents.qa.logic import QualityAgentMixin
    from packages.agents.writer.dimension_writer import DimensionWriterMixin
    from packages.orchestrator.llm_execution import LLMExecutionMixin
    from packages.orchestrator.service import RunService

    assert module.RunService is RunService
    assert RunService._trace_llm_json is LLMExecutionMixin._trace_llm_json
    assert RunService._trace_llm_text is LLMExecutionMixin._trace_llm_text
    assert RunService._real_qa_step is QualityAgentMixin._real_qa_step
    assert RunService._writer_dimension_report is DimensionWriterMixin._writer_dimension_report
    source = SCRIPT.read_text()
    assert "InputReplay" not in source
    assert "service._llm =" not in source
    assert "monthly_token_quota" not in source


def test_settings_keep_credentials_and_bound_all_transport(monkeypatch, tmp_path):
    module = runner()
    from packages.config import Settings

    original = Settings(
        ark_api_key="unit-only-key", ark_model="deepseek-unit-proxy", llm_provider_name="deepseek"
    )
    monkeypatch.setattr(module, "get_settings", lambda: original)
    settings = module.live_settings(tmp_path)
    assert settings.ark_api_key == original.ark_api_key
    assert settings.ark_model == original.ark_model
    assert (
        settings.run_llm_max_calls,
        settings.run_llm_max_tokens,
        settings.llm_max_output_tokens,
    ) == (24, 80000, 2048)
    assert settings.llm_max_retries == settings.run_llm_max_repairs == 0
    assert settings.backup_llm_api_key is None
    assert settings.analyst_react_enabled is False


def test_native_downstream_diagnostic_writes_real_artifacts_without_search(monkeypatch, tmp_path):
    module = runner()
    from packages.config import Settings
    from packages.llm.execution_budget import current_llm_execution
    from packages.search.deepseek_client import DeepSeekSearchClient
    from packages.search.perplexity_client import PerplexitySearchClient

    prompts = []

    class UnitModel:
        async def complete_json(self, **kwargs):
            current_llm_execution.get().reserve_transport()
            prompts.append(json.dumps(kwargs))
            return {}

        async def complete_text(self, **kwargs):
            current_llm_execution.get().reserve_transport()
            prompts.append(json.dumps(kwargs))
            from claim_review_fixture import expand_prompt_payload, question_plan_response
            payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
            return question_plan_response(payload, [])

    production_service = module.RunService

    def unit_service(*args, **kwargs):
        service = production_service(*args, **kwargs)
        service._llm = UnitModel()  # Unit boundary only; live runner never replaces its model.
        return service

    async def no_search(*args, **kwargs):
        pytest.fail("fixed excerpt diagnostic attempted online search")

    monkeypatch.setattr(module, "RunService", unit_service)
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: Settings(
            ark_api_key="unit-only-key",
            ark_model="deepseek-unit-proxy",
            llm_provider_name="deepseek",
        ),
    )
    monkeypatch.setattr(DeepSeekSearchClient, "search", no_search)
    monkeypatch.setattr(PerplexitySearchClient, "search", no_search)
    rows = [module.allowed_payload(row) for row in cases() if row["id"] in module.SCORED]
    output = tmp_path / "diagnostic"
    result = asyncio.run(module.run_diagnostic(rows, output, timeout=30))
    assert result["error_type"] is None
    assert result["report_chars"] > 0  # A gap-only draft is useful, but is not deliverable.
    assert result["collector_status"] == "skipped" and result["deliverable"] is False
    assert result["semantic_quality"] == "pending_human"
    assert 0 < result["llm_transport_attempts"] <= 24
    assert result["provider_total_tokens_last_attempts"] is None
    assert {
        "run.json",
        "events.json",
        "snapshot.json",
        "report.md",
        "summary.json",
        "manifest.json",
        "inputs.json",
        "extractions.json",
        "canonical.sqlite",
    } <= {path.name for path in output.iterdir()}
    raw = json.loads((output / "run.json").read_text())["detail"]
    assert raw["evidence_consumptions"] and raw["evidence_snapshots"]
    assert {span["agent"] for span in raw["trace_spans"] if span["kind"] == "llm"} >= {
        "analyst",
        "comparator",
        "reflector",
    }
    writer_spans = [span for span in raw["trace_spans"] if span["kind"] == "llm" and span["agent"] == "writer"
                    and (span["metadata"].get("llm_transport_attempts", 0) or 0) > 0]
    writer_attempts = sum(span["metadata"]["llm_transport_attempts"] for span in writer_spans)
    assert writer_spans and writer_attempts > 0
    assert result["downstream_observations"]["llm_transport_by_agent"]["writer"] == writer_attempts
    assert result["downstream_observations"]["reviewed_claim_count"] == 0
    assert result["downstream_observations"]["llm_transport_by_agent"]["collector"] == 0
    assert any(
        event["message"].startswith("QA completed")
        for event in json.loads((output / "events.json").read_text())
    )
    sent = "\n".join(prompts)
    for row in cases():
        assert row["reference_answer"] not in sent
        for field in ("required_conditions", "forbidden_inferences"):
            assert all(item not in sent for item in row[field])
    assert "unit-only-key" not in "\n".join(path.read_text() for path in output.glob("*.json"))


def test_fixture_time_does_not_impersonate_original_verification():
    from datetime import UTC, datetime

    module = runner()
    payload = module.allowed_payload(cases()[0])
    before = datetime.now(UTC)
    mapped = module.map_excerpt(payload, payload["sources"][0])
    assert mapped["capture"].captured_at >= before
    assert (
        mapped["raw_source"].metadata["source_verified_at"] == payload["sources"][0]["verified_at"]
    )


def test_canonical_ingestion_failure_preserves_blocked_artifacts(monkeypatch, tmp_path):
    module = runner()
    import packages.tools.ingest_document as ingestion
    from packages.config import Settings

    async def unavailable(**kwargs):
        raise RuntimeError("unit canonical storage unavailable")

    monkeypatch.setattr(ingestion, "ingest_document_reference", unavailable)
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: Settings(
            ark_api_key="unit-only-key",
            ark_model="deepseek-unit-proxy",
            llm_provider_name="deepseek",
        ),
    )
    payload = module.allowed_payload(cases()[0])
    result = asyncio.run(module.run_diagnostic([payload], tmp_path / "unavailable"))
    assert result["status"] == "blocked"
    assert result["error_reason"] == "unit canonical storage unavailable"
    assert result["llm_transport_attempts"] == 0
    assert (tmp_path / "unavailable/summary.json").is_file()


def anonymous_excerpt_mapping(module, *, excerpt='Guests can edit documents after signing in.',
                              url='https://example.test/permissions', question='Can Guests edit documents?',
                              source_id='anonymous-source'):
    case = {'product': 'Example Product', 'question': question}
    source = dict(id=source_id, title='Original permission rule', url=url, excerpt=excerpt,
                  verified_at='2026-10-16T12:00:00Z', source_role='source')
    return module.map_excerpt(case, source)


def test_excerpt_slots_follow_original_source_and_excerpt_identity_only():
    module = runner()
    first = anonymous_excerpt_mapping(module)
    same = anonymous_excerpt_mapping(module, question='A different user question?', source_id='alias-source')
    changed_excerpt = anonymous_excerpt_mapping(module, excerpt='Guests can comment on documents after signing in.')
    changed_source = anonymous_excerpt_mapping(module, url='https://example.test/another-rule')
    rows = [item['raw_source'].metadata['normalized_fields'][0] for item in [first, same, changed_excerpt, changed_source]]
    assert isinstance(rows[0]['slot'], str) and rows[0]['slot']
    assert rows[0]['slot'] == rows[1]['slot']
    assert len({rows[0]['slot'], rows[2]['slot'], rows[3]['slot']}) == 3
    assert all(row['evidence_terms'] == [item['source']['excerpt']]
               for row, item in zip(rows, [first, same, changed_excerpt, changed_source]))
    for item in [first, same, changed_excerpt, changed_source]:
        module.validate_mapping(item)


@pytest.mark.parametrize('slot', ['foreign-slot', None])
def test_excerpt_mapping_validator_recomputes_slot_instead_of_trusting_foreign_slot(slot):
    module = runner()
    mapped = anonymous_excerpt_mapping(module)
    mapped['raw_source'].metadata['normalized_fields'][0]['slot'] = slot
    with pytest.raises(ValueError, match='binding'):
        module.validate_mapping(mapped)


def test_independent_excerpt_slots_keep_real_same_slot_conflicts_excluded():
    from test_question_retrieval import research_case, replace_snapshot
    from packages.agents.writer.question_retrieval import _eligible_facts
    from packages.research.evidence.snapshot import _conflicts
    from packages.research.evidence.snapshot_models import canonical_json

    module = runner()
    texts = ['Guests can edit documents after signing in.',
             'Guests can only view documents after accepting the invitation.']
    mapped = [anonymous_excerpt_mapping(module, excerpt=text) for text in texts]
    assert all(item['raw_source'].metadata['normalized_fields'] for item in mapped), [
        [row.rejection_reason for row in item['items']] for item in mapped]
    slots = [item['raw_source'].metadata['normalized_fields'][0]['slot'] for item in mapped]
    detail, snapshot = research_case(texts, question='Example Product: Can Guests edit documents?')
    originals = [row for row in snapshot.facts if row.field == 'evidence_terms']
    independent = tuple(row.model_copy(update={'qualifiers_json': canonical_json({'slot': slot})})
                        for row, slot in zip(originals, slots))
    conflicts = _conflicts(independent)
    assert not conflicts
    independent_snapshot = replace_snapshot(detail, snapshot, facts=independent, conflicts=conflicts)
    assert {row.id for row in _eligible_facts(independent_snapshot, 'Example Product', 'feature')} == {
        row.id for row in independent}
    same_slot = tuple(row.model_copy(update={'qualifiers_json': canonical_json({'slot': slots[0]})})
                      for row in independent)
    conflicts = _conflicts(same_slot)
    assert conflicts and set(conflicts[0].fact_ids) == {row.id for row in same_slot}
    conflicting_snapshot = replace_snapshot(detail, independent_snapshot, facts=same_slot, conflicts=conflicts)
    assert not _eligible_facts(conflicting_snapshot, 'Example Product', 'feature')
