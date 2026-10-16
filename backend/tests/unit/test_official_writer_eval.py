import asyncio
import importlib
import json

import pytest


def test_preview_has_no_configuration_fetch_or_model_access(monkeypatch, capsys):
    module = importlib.import_module("scripts.eval_official_writer")
    monkeypatch.setattr(module, "run_live", lambda *a, **k: pytest.fail("live executed"))
    asyncio.run(module.main([]))
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "list_only"
    assert result["llm_transport_attempts"] == result["fetch_attempts"] == 0
    assert result["reviewed_cases"] == 8
    assert len(result["case_ids"]) == len(result["source_urls"]) == 4
    assert len(result["registry_sha256"]) == 64


def test_live_requires_both_frozen_hashes_before_runtime(monkeypatch):
    module = importlib.import_module("scripts.eval_official_writer")
    monkeypatch.setattr(module, "run_live", lambda *a, **k: pytest.fail("live executed"))
    with pytest.raises(ValueError, match="requires"):
        asyncio.run(module.main(["--live"]))


def test_model_payload_excludes_answers_and_curated_excerpts():
    module = importlib.import_module("scripts.eval_official_writer")
    payloads, manifest = module.prepare_inputs(module.ROOT / "eval/product-condition-review-v1.jsonl")
    text = json.dumps(payloads)
    for forbidden in ("reference_answer", "expected_outcome", "required_conditions",
                      "forbidden_inferences", "excerpt", "reviewed_by"):
        assert forbidden not in text
    assert manifest["semantic_quality"] == "pending_human"


def test_candidate_inputs_rejected_before_live():
    module = importlib.import_module("scripts.eval_official_writer")
    with pytest.raises(ValueError, match="human review"):
        module.prepare_inputs(module.ROOT / "eval/archive/product-condition-review-v1-candidate/cases.jsonl")


def test_diagnostic_disables_inherited_remote_vector_indexing(monkeypatch, tmp_path):
    module = importlib.import_module("scripts.eval_official_writer")
    from packages.knowledge.runtime import semantic_indexing_enabled
    monkeypatch.setenv('KB_RETRIEVAL_MODE', 'hybrid')
    monkeypatch.setenv('KB_EMBEDDING_PROVIDER', 'http')
    with module.diagnostic_environment(tmp_path):
        assert not semantic_indexing_enabled()
    assert semantic_indexing_enabled()


@pytest.mark.asyncio
async def test_capture_only_honors_total_timeout_and_preserves_partial_results(monkeypatch, tmp_path):
    module = importlib.import_module('scripts.eval_official_writer')
    from packages.config import Settings
    settings = Settings(demo_mode=False, ark_api_key='unit-only', ark_model='unit-model',
                        llm_provider_name='deepseek', run_orchestration_backend='langgraph')
    monkeypatch.setattr(module, 'live_settings', lambda output: settings)
    async def slow_fetch(*args, **kwargs):
        await asyncio.sleep(1)
        pytest.fail('fetch did not stop')
    monkeypatch.setattr(module.RunService, '_trace_fetch', slow_fetch)
    payloads, manifest = module.prepare_inputs(module.ROOT / 'eval/product-condition-review-v1.jsonl')
    output = tmp_path / 'run'
    summary = await module.run_live(payloads, manifest, output, timeout=.02, capture_only=True)
    assert summary['error_type'] == 'TimeoutError'
    assert summary['status'] == 'blocked'
    assert json.loads((output / 'captures.json').read_text()) == []


@pytest.mark.asyncio
async def test_stage_runner_commits_writer_producer_and_always_runs_qa(monkeypatch):
    from types import SimpleNamespace
    module = importlib.import_module('scripts.eval_official_writer')
    seen = []
    async def collect(*args):
        seen.append('collect')
    monkeypatch.setattr(module, 'collect_sources', collect)
    class Service:
        def __getattr__(self, name):
            async def step(*args, **kwargs):
                seen.append(name)
                assert name != '_write_report_draft', 'must use guarded producer commit'
            return step
    record = SimpleNamespace(detail=SimpleNamespace(raw_sources=[object()], plan=SimpleNamespace(competitors=['Miro'])))
    await module.execute_stages(Service(), record, [])
    assert '_real_phase_qa_step' in seen
    assert seen.index('_real_phase_qa_step') < seen.index('_real_writer_step')
    assert '_real_writer_step' in seen
    assert seen[-1] == '_real_qa_step'


@pytest.mark.asyncio
async def test_no_admitted_sources_stops_before_paid_downstream_calls(monkeypatch):
    from types import SimpleNamespace
    module = importlib.import_module('scripts.eval_official_writer')
    seen = []
    async def empty(*args):
        pass
    monkeypatch.setattr(module, 'collect_sources', empty)
    class Service:
        def __getattr__(self, name):
            async def step(*args, **kwargs):
                seen.append(name)
            return step
    record = SimpleNamespace(detail=SimpleNamespace(raw_sources=[], plan=SimpleNamespace(competitors=['Miro'])))
    with pytest.raises(ValueError, match='no_accepted_sources'):
        await module.execute_stages(Service(), record, [])
    assert seen == ['_real_qa_step']


def test_legacy_no_artifact_default_does_not_count_as_writer_producer():
    from types import SimpleNamespace
    module = importlib.import_module('scripts.eval_official_writer')
    record = SimpleNamespace(detail=SimpleNamespace(evidence_artifact_dependencies=[]))
    service = SimpleNamespace(_final_qa_producer_verified=lambda *a: True)
    assert not module.writer_producer_verified(service, record, object())
