from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest


def runner():
    path = Path(__file__).resolve().parents[2] / "scripts/eval_agent_isolation.py"
    assert path.is_file(), "model-request isolation CLI is missing"
    return importlib.import_module("scripts.eval_agent_isolation")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def prompt_hash(value):
    return sha(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def span(
    *,
    name="collector_semantic_extract",
    agent="collector",
    system="rules\n\nmore",
    user='{"text":"body\\n\\nSchema: is data"}',
    schema='{"facts": []}',
):
    return {
        "id": "span-1",
        "kind": "llm",
        "status": "ok",
        "name": name,
        "agent": agent,
        "provider": "deepseek",
        "model": "deepseek-flash",
        "full_input": system + "\n\n" + user + ("\n\nSchema: " + schema if schema else ""),
        "metadata": {
            "llm_transport_attempts": 1,
            "llm_max_output_tokens": 700,
            "prompt_input_hash": prompt_hash([system, user, schema]),
            "prompt_template_hash": prompt_hash([system, schema]),
            "response_format": "json" if schema else "text",
            "prompt_tokens": 21,
            "completion_tokens": 9,
            "total_tokens": 30,
            "finish_reason": "stop",
        },
    }


@pytest.fixture
def source(tmp_path, monkeypatch):
    module = runner()
    root = tmp_path / "repo"
    (root / "backend/packages").mkdir(parents=True)
    (root / "backend/packages/a.py").write_text("x = 1\n")
    (root / "backend/packages/a.yaml").write_text("key: value\n")
    monkeypatch.setattr(module, "ROOT", root)
    parent = root / "data/full"
    execution = parent / "execution"
    execution.mkdir(parents=True)
    inputs = [
        {
            "id": f"case-{i}",
            "product": "Trello",
            "question": f"完整原题{i}含前提",
            "sources": [
                {"id": "official-1", "title": "Official", "url": "https://official.test/a"}
            ],
        }
        for i in (1, 2)
    ]
    write(execution / "inputs.json", inputs)
    canonical = {
        "id": "current",
        "competitors": ["Trello"],
        "sources": [
            {
                "id": "raw-1",
                "competitor": "Trello",
                "title": "Official",
                "url": "https://official.test/a",
                "content_hash": "hash",
                "payload_json": "MUST_NOT_ENTER_SINGLE",
            }
        ],
        "facts": [
            {
                "id": "fact-1",
                "source_id": "raw-1",
                "competitor": "Trello",
                "dimension": "feature",
                "field": "permissions",
                "value_json": '["can export"]',
                "quote": "can export if enabled",
                "qualifiers_json": (
                    '{"plan":"Premium","operations":[{"prerequisites":["enabled"]}]}'
                ),
                "status": "supported",
            }
        ],
    }
    write(execution / "snapshot.json", [{"id": "old", "facts": [{"quote": "OLD_FACT"}]}, canonical])
    write(
        execution / "run.json",
        {
            "status": "queued",
            "evidence_snapshot_id": "current",
            "report_md": "OLD_REPORT",
            "llm_budget_checkpoint": {"calls": 22, "tokens_used": 72000},
        },
    )
    write(execution / "trace.json", [span()])
    (execution / "report.md").write_text("OLD_REPORT")
    write(
        execution / "summary.json",
        {
            "status": "execution_complete",
            "capture_only": False,
            "replay_network_guard_blocks": 0,
            "production_code_changed_during_run": False,
        },
    )
    hashes = module.code_hashes()
    manifest = {
        **hashes,
        "input_sha256": sha((execution / "inputs.json").read_bytes()),
        "case_ids": [item["id"] for item in inputs],
        "pipeline_nodes": list(module.ROLES),
        "model_parameters": {
            "provider": "deepseek",
            "model": "deepseek-flash",
            "temperature": 0,
            "default_max_output_tokens": 2048,
            "retries": 0,
        },
    }
    write(execution / "manifest.json", manifest)
    write(parent / "manifest.json", manifest)
    write(parent / "production-hashes.json", hashes)
    write(parent / "production-hashes-after.json", hashes)
    return execution


def test_preflight_has_zero_model_calls_without_loading_settings(source, tmp_path, monkeypatch):
    module = runner()
    import packages.config as config

    monkeypatch.setattr(config, "get_settings", lambda: pytest.fail("preflight loaded credentials"))
    monkeypatch.setattr(
        module, "load_live_settings", lambda *_: pytest.fail("live settings loaded")
    )
    monkeypatch.setattr(module, "create_client", lambda *_: pytest.fail("client created"))
    result = asyncio.run(module.run_diagnostic(source, tmp_path / "out", mode="single"))
    assert result["status"] == "preflight_passed"
    assert result["llm_transport_attempts"] == 0
    assert result["live"] is False
    assert result["source_file_sha256"]


@pytest.mark.parametrize(
    "file,field,value",
    [
        ("summary.json", "status", "failed"),
        ("summary.json", "status", "completed"),
        ("summary.json", "capture_only", True),
        ("summary.json", "capture_only", None),
        ("summary.json", "replay_network_guard_blocks", 1),
        ("summary.json", "replay_network_guard_blocks", None),
        ("summary.json", "production_code_changed_during_run", True),
        ("summary.json", "production_code_changed_during_run", None),
        ("manifest.json", "pipeline_nodes", ["collector", "writer"]),
        ("manifest.json", "pipeline_nodes", None),
        ("run.json", "status", "failed"),
        ("run.json", "status", "cancelled"),
        ("run.json", "status", "error"),
    ],
)
def test_preflight_requires_completed_unchanged_full_source(source, file, field, value):
    path = source / file
    data = json.loads(path.read_text())
    data[field] = value
    write(path, data)
    with pytest.raises(ValueError, match="source.*(execution|pipeline)"):
        runner().preflight(source, mode="single")


def test_queued_detail_is_allowed_when_the_frozen_runner_completed(source):
    assert runner().preflight(source, mode="single")["requests"]


def test_outer_manifest_must_declare_full_pipeline(source):
    path = source.parent / "manifest.json"
    data = json.loads(path.read_text())
    data["pipeline_nodes"] = ["collector"]
    write(path, data)
    with pytest.raises(ValueError, match="source.*pipeline"):
        runner().preflight(source, mode="single")


def test_reconstructs_actual_messages_despite_multiple_blank_lines_and_schema_text():
    module = runner()
    source_span = span(user="part one\n\nSchema: this is user data\n\npart two")
    request = module.recover_request(source_span)
    assert request["system"] == "rules\n\nmore"
    assert request["user"] == "part one\n\nSchema: this is user data\n\npart two"
    assert request["schema"] == '{"facts": []}'
    assert request["messages"][0]["content"] == (
        "rules\n\nmore\n\nReturn only valid JSON. Do not wrap it in markdown fences. "
        'The JSON shape is: {"facts": []}'
    )


def test_recovery_enumerates_overlapping_blank_line_boundaries():
    value = span(system="rules\n", user="\nbody", schema=None)
    request = runner().recover_request(value)
    assert request["system"] == "rules\n"
    assert request["user"] == "\nbody"


@pytest.mark.parametrize("mutation", ["no_transport", "bad_hash", "bad_template", "redacted"])
def test_request_recovery_rejects_unproven_or_modified_request(mutation):
    value = span()
    if mutation == "no_transport":
        value["metadata"]["llm_transport_attempts"] = 0
    elif mutation == "bad_hash":
        value["metadata"]["prompt_input_hash"] = "bad"
    elif mutation == "bad_template":
        value["metadata"]["prompt_template_hash"] = "bad"
    else:
        value["full_input"] = value["full_input"].replace("rules", "[REDACTED]")
    with pytest.raises(ValueError):
        runner().recover_request(value)


def test_single_uses_current_facts_complete_questions_and_source_identity_only(source):
    request = runner().preflight(source, mode="single")["requests"][0]
    payload = json.loads(request["user"])
    assert [q["question"] for q in payload["questions"]] == ["完整原题1含前提", "完整原题2含前提"]
    assert payload["facts"][0]["quote"] == "can export if enabled"
    assert payload["facts"][0]["qualifiers"]["operations"][0]["prerequisites"] == ["enabled"]
    assert payload["sources"][0]["id"] == "raw-1"
    assert all(
        x not in request["user"] for x in ("OLD_REPORT", "OLD_FACT", "MUST_NOT_ENTER_SINGLE")
    )
    assert request["max_output_tokens"] == 2048


def shared_single_payload():
    condition = {
        "plan": "Premium",
        "operations": [
            {
                "operation": "export",
                "effect": "allowed",
                "role": "administrator",
                "prerequisites": [
                    "Only if the administrator enables the full export setting. " * 8
                ],
                "exceptions": [
                    "Except when the complete organization policy forbids this operation."
                ],
            }
        ],
    }
    return {
        "evidence_snapshot_id": "current",
        "questions": [
            {"id": f"question-{i}", "question": f"完整原题{i}与全部前提"} for i in (1, 2)
        ],
        "sources": [{"id": "source-1", "url": "https://official.test/a"}],
        "facts": [
            {
                "id": f"fact-{i}",
                "source_id": "source-1",
                "quote": f"Complete quote {i}.",
                "value": [condition, condition],
                "qualifiers": deepcopy(condition),
            }
            for i in range(84)
        ],
    }


def test_large_single_payload_restores_every_fact_condition_question_and_hash():
    module = runner()
    original = shared_single_payload()
    encoded, metadata = module.encode_single_payload(original)
    payload = json.loads(encoded)
    restored = module.decode_single_payload(
        payload,
        payload_sha256=metadata["single_payload_sha256"],
        facts_sha256=metadata["single_facts_sha256"],
    )
    assert len(module.compact(original).encode()) >= 172000
    assert len(restored["facts"]) == 84
    assert restored == original
    assert metadata["single_roundtrip_verified"] is True
    assert metadata["single_payload_sha256"] == sha(module.compact(restored).encode())
    assert metadata["single_facts_sha256"] == sha(module.compact(restored["facts"]).encode())
    assert metadata["input_encoding"] == "shared_values_and_text_sets.v1"
    assert all(f["source_id"] == "source-1" and isinstance(f["id"], str) for f in payload["facts"])
    assert (
        module.logical_input_tokens(
            {
                "messages": [
                    {"role": "system", "content": module.SINGLE_SYSTEM},
                    {"role": "user", "content": encoded},
                ]
            }
        )
        + 2048
        < 80000
    )


def test_nested_shared_conditions_are_a_lossless_dag():
    module = runner()
    original = shared_single_payload()
    encoded, _ = module.encode_single_payload(original)
    payload = json.loads(encoded)
    assert payload["shared_values"]
    assert any(
        "shared_value_ref" in module.compact(value) for value in payload["shared_values"].values()
    )
    assert module.decode_single_payload(payload) == original


def test_nonrepeated_single_payload_does_not_grow():
    module = runner()
    original = {
        "evidence_snapshot_id": "current",
        "questions": ["完整原题"],
        "sources": [{"id": "source-1"}],
        "facts": [{"quote": "Unique. " * 50}],
    }
    encoded, metadata = module.encode_single_payload(original)
    assert encoded == module.compact(original)
    assert metadata["input_encoding"] == "literal_json.v1"
    assert module.decode_single_payload(json.loads(encoded)) == original


@pytest.mark.parametrize(
    "mutation", ["missing", "cycle", "ambiguous", "missing_text", "nested_table"]
)
def test_single_shared_reference_corruption_is_rejected(mutation):
    module = runner()
    encoded, _ = module.encode_single_payload(shared_single_payload())
    payload = json.loads(encoded)
    ref = next(iter(payload["shared_values"]))
    if mutation == "missing":
        payload["facts"][0]["qualifiers"] = {"shared_value_ref": "missing"}
    elif mutation == "cycle":
        payload["shared_values"][ref] = {"shared_value_ref": ref}
    elif mutation == "ambiguous":
        payload["facts"][0]["qualifiers"] = {"shared_value_ref": ref, "extra": True}
    elif mutation == "missing_text":
        payload["facts"][0]["quote"] = {"text_ref": "missing"}
    else:
        payload["facts"][0]["qualifiers"] = {"text_sets": {"bad": "ambiguous"}}
    with pytest.raises(ValueError):
        module.decode_single_payload(payload)


@pytest.mark.parametrize("sentinel", ["shared_value_ref", "shared_values", "text_ref", "text_sets"])
def test_original_data_cannot_ambiguously_supply_encoding_sentinels(sentinel):
    original = shared_single_payload()
    original["facts"][0]["qualifiers"] = {sentinel: "literal data"}
    with pytest.raises(ValueError, match="reserved|ambiguous"):
        runner().encode_single_payload(original)


def test_single_decoder_checks_payload_and_facts_hashes():
    module = runner()
    encoded, metadata = module.encode_single_payload(shared_single_payload())
    payload = json.loads(encoded)
    payload["facts"][0]["quote"] = "tampered complete quote"
    for hashes in (
        {"payload_sha256": metadata["single_payload_sha256"]},
        {"facts_sha256": metadata["single_facts_sha256"]},
    ):
        with pytest.raises(ValueError, match="hash"):
            module.decode_single_payload(payload, **hashes)


def test_runtime_roundtrip_failure_blocks_without_settings_or_transport(
    source, tmp_path, monkeypatch
):
    module = runner()
    monkeypatch.setattr(module, "decode_single_payload", lambda *_args, **_kwargs: {"facts": []})
    monkeypatch.setattr(module, "load_live_settings", lambda *_: pytest.fail("settings loaded"))
    result = asyncio.run(
        module.run_diagnostic(source, tmp_path / "bad-roundtrip", mode="single", live=True)
    )
    assert result["status"] == "blocked"
    assert result["llm_transport_attempts"] == 0


def test_reservation_uses_logical_message_bytes_without_http_double_escaping(source):
    module = runner()
    request = module.preflight(source, mode="isolate", role="collector")["requests"][0]
    expected = sum(len(message["content"].encode()) for message in request["messages"]) + 256
    assert request["input_tokens_reserved"] == expected
    assert request["metadata"]["input_reservation_method"] == "logical_message_utf8_bytes_plus_256"
    assert request["messages"] == module.recover_request(span())["messages"]


def test_unknown_usage_charges_full_new_message_reservation(source, tmp_path, monkeypatch):
    module = runner()
    install_live(monkeypatch)
    output = tmp_path / "unknown-reservation"
    result = asyncio.run(module.run_diagnostic(source, output, mode="single", live=True))
    call = json.loads((output / "calls.json").read_text())[0]
    expected = module.logical_input_tokens(call) + 2048
    assert call["budget"]["llm_tokens_charged"] == expected
    assert result["diagnostic_budget"]["tokens_charged"] == expected
    assert result["diagnostic_cost"]["usage_unknown_count"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "extra_gold",
        "source_gold",
        "foreign_source",
        "foreign_fact",
        "wrong_product",
        "code_hash",
        "input_hash",
        "missing_parameters",
        "bad_parameters",
        "changed_hashes",
    ],
)
def test_preflight_rejects_contamination_or_frozen_binding_mismatch(source, mutation):
    if mutation in {"extra_gold", "source_gold"}:
        path = source / "inputs.json"
        value = json.loads(path.read_text())
        target = value[0] if mutation == "extra_gold" else value[0]["sources"][0]
        target["reference_answer"] = "DO_NOT_SEND"
    elif mutation in {"foreign_source", "foreign_fact", "wrong_product"}:
        path = source / "snapshot.json"
        value = json.loads(path.read_text())
        if mutation == "foreign_source":
            value[-1]["sources"][0]["url"] = "https://foreign.test/"
        elif mutation == "foreign_fact":
            value[-1]["facts"][0]["source_id"] = "foreign"
        else:
            value[-1]["facts"][0]["competitor"] = "Miro"
    elif mutation == "changed_hashes":
        path = source.parent / "production-hashes-after.json"
        value = {"production_code_sha256": "changed"}
    else:
        path = source / "manifest.json"
        value = json.loads(path.read_text())
        if mutation == "missing_parameters":
            del value["model_parameters"]
        elif mutation == "bad_parameters":
            value["model_parameters"]["temperature"] = 0.4
        else:
            value["production_code_sha256" if mutation == "code_hash" else "input_sha256"] = (
                "changed"
            )
    write(path, value)
    with pytest.raises(ValueError):
        runner().preflight(source, mode="single")


def test_missing_actual_role_is_not_exercised(source, tmp_path):
    result = asyncio.run(
        runner().run_diagnostic(source, tmp_path / "missing", mode="isolate", role="planner")
    )
    assert result["status"] == "not_exercised"
    assert result["roles"]["planner"] == "not_exercised"
    assert result["llm_transport_attempts"] == 0


@pytest.mark.parametrize(
    "name", ["dimension_task_generation", "dimension_question_atomic_generation"]
)
def test_writer_generation_recovers_exact_actual_request(source, name):
    module = runner()
    system = "Writer rules\n\nretain every condition"
    user = "完整问题\n\nSchema: user data\n\n原始证据"
    schema = '{"answers": []}'
    value = span(name=name, agent="writer", system=system, user=user, schema=schema)
    write(source / "trace.json", [value])

    plan = module.preflight(source, mode="isolate", role="writer")

    assert module.NAMES["writer"] == "dimension_task_generation"
    assert plan["roles"] == {"writer": "ready"}
    assert len(plan["requests"]) == 1
    request = plan["requests"][0]
    assert request["system"] == system
    assert request["user"] == user
    assert request["schema"] == schema
    assert request["messages"] == [
        {"role": "system", "content": system + module.JSON_INSTRUCTION + schema},
        {"role": "user", "content": user},
    ]
    assert request["source_span_id"] == value["id"]
    assert request["max_output_tokens"] == 700


@pytest.mark.parametrize(
    "name,attempts,kind,status",
    [
        ("dimension_question_atomic_generation", 0, "llm", "ok"),
        ("dimension_task_generation", 0, "llm", "ok"),
        ("dimension_question_atomic_generation", 1, "agent", "ok"),
        ("dimension_question_atomic_generation", 1, "llm", "error"),
        ("dimension_question_atomic_review", 1, "llm", "ok"),
        ("dimension_question_atomic_answer_review", 1, "llm", "ok"),
    ],
)
def test_writer_without_actual_successful_generation_is_not_exercised(
    source, name, attempts, kind, status
):
    value = span(name=name, agent="writer")
    value["metadata"]["llm_transport_attempts"] = attempts
    value.update(kind=kind, status=status)
    write(source / "trace.json", [value])

    plan = runner().preflight(source, mode="isolate", role="writer")

    assert plan["roles"] == {"writer": "not_exercised"}
    assert plan["requests"] == []


@pytest.mark.parametrize(
    "first_name,second_name",
    [
        ("dimension_question_atomic_generation", "dimension_task_generation"),
        ("dimension_task_generation", "dimension_question_atomic_generation"),
    ],
)
def test_writer_selects_first_actual_generation_without_judging_output(
    source, first_name, second_name
):
    skipped = span(name=first_name, agent="writer", user="no actual request")
    skipped["metadata"]["llm_transport_attempts"] = 0
    review = span(name="dimension_question_atomic_review", agent="writer", user="review")
    first = span(name=first_name, agent="writer", user="first actual request")
    first.update(id="first", full_output="broken {")
    second = span(name=second_name, agent="writer", user="second actual request")
    second.update(id="second", full_output='{"answers": []}')
    write(source / "trace.json", [skipped, review, first, second])

    plan = runner().preflight(source, mode="isolate", role="writer")

    assert plan["roles"] == {"writer": "ready"}
    assert len(plan["requests"]) == 1
    assert plan["requests"][0]["source_span_id"] == "first"
    assert plan["requests"][0]["user"] == "first actual request"


def test_output_cannot_overwrite_source_or_history(source, tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "marker").write_text("keep")
    for output in (source, source / "child", source.parent, old):
        with pytest.raises(ValueError):
            asyncio.run(runner().run_diagnostic(source, output, mode="single"))
    assert (old / "marker").read_text() == "keep"


@dataclass
class Settings:
    llm_provider_name: str = "deepseek"
    ark_model: str = "deepseek-flash"
    ark_base_url: str = "https://api.test/v1"
    ark_api_key: str = "DO_NOT_PERSIST_CREDENTIAL"
    llm_temperature: float = 0
    llm_max_output_tokens: int = 2048
    llm_max_retries: int = 0
    llm_timeout_seconds: int = 5
    run_llm_max_tokens: int = 80000
    run_llm_max_cost_usd: int = 0
    backup_llm_api_key: str | None = None
    backup_llm_model: str | None = None


def install_live(monkeypatch, *, content='{"facts": []}', finish="stop", usage=None, callback=None):
    module = runner()
    monkeypatch.setattr(module, "load_live_settings", lambda *_: Settings())
    from packages.llm import DoubaoClient
    from packages.llm.doubao_client import LLMProviderConfig

    monkeypatch.setattr(
        DoubaoClient,
        "_provider_configs",
        lambda self: [
            LLMProviderConfig(
                "deepseek",
                "primary",
                "DO_NOT_PERSIST_CREDENTIAL",
                "https://api.test/v1",
                "deepseek-flash",
            )
        ],
    )

    async def send(self, request, **kwargs):
        if callback:
            callback(request)
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": finish}],
                "usage": usage,
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", send)


@pytest.mark.parametrize(
    "finish,content,usage,expected",
    [
        ("stop", "broken {", {"prompt_tokens": 30, "completion_tokens": 4}, "invalid_response"),
        ("length", '{"facts": [', {"prompt_tokens": 30, "completion_tokens": 700}, "length"),
        ("stop", '{"facts": []}', None, "diagnostic_complete"),
    ],
)
def test_live_preserves_raw_failure_usage_and_independent_budget(
    source, tmp_path, monkeypatch, finish, content, usage, expected
):
    install_live(monkeypatch, content=content, finish=finish, usage=usage)
    output = tmp_path / "live"
    result = asyncio.run(
        runner().run_diagnostic(source, output, mode="isolate", role="collector", live=True)
    )
    call = json.loads((output / "calls.json").read_text())[0]
    assert result["status"] == expected
    assert call["raw_output"] == content
    assert call["finish_reason"] == finish
    assert call["usage"]["prompt_tokens"] == (30 if usage else None)
    assert call["usage_unknown"] is (usage is None)
    assert call["budget"]["llm_tokens_charged"] > 0
    assert call["budget"]["llm_transport_attempts"] == 1
    assert result["diagnostic_budget"]["calls"] == 1
    assert "DO_NOT_PERSIST_CREDENTIAL" not in "".join(p.read_text() for p in output.iterdir())
    assert json.loads((source / "run.json").read_text())["llm_budget_checkpoint"]["calls"] == 22


def test_current_model_mismatch_blocks_before_transport(source, tmp_path, monkeypatch):
    module = runner()
    monkeypatch.setattr(module, "load_live_settings", lambda *_: Settings(ark_model="different"))
    monkeypatch.setattr(
        module, "create_client", lambda *_: pytest.fail("mismatched model dispatched")
    )
    result = asyncio.run(
        module.run_diagnostic(source, tmp_path / "mismatch", mode="single", live=True)
    )
    assert result["status"] == "blocked"
    assert result["llm_transport_attempts"] == 0


def test_malformed_provider_usage_remains_unknown_and_conservatively_charged(
    source, tmp_path, monkeypatch
):
    install_live(monkeypatch, usage={"prompt_tokens": "bad", "completion_tokens": -1})
    result = asyncio.run(
        runner().run_diagnostic(
            source, tmp_path / "bad-usage", mode="isolate", role="collector", live=True
        )
    )
    assert result["status"] == "diagnostic_complete"
    assert result["diagnostic_cost"]["usage_unknown_count"] == 1
    assert result["diagnostic_cost"]["known_prompt_tokens"] == 0
    assert result["diagnostic_budget"]["tokens_charged"] > 700


def test_model_echoed_credentials_are_redacted_from_saved_response(source, tmp_path, monkeypatch):
    install_live(monkeypatch, content="echo DO_NOT_PERSIST_CREDENTIAL")
    output = tmp_path / "echo"
    asyncio.run(runner().run_diagnostic(source, output, mode="single", live=True))
    assert "DO_NOT_PERSIST_CREDENTIAL" not in "".join(p.read_text() for p in output.iterdir())


@pytest.mark.parametrize(
    "finish", ["DO_NOT_PERSIST_CREDENTIAL", {"bad": "DO_NOT_PERSIST_CREDENTIAL"}]
)
def test_unknown_finish_reason_is_safe_and_cannot_pass(source, tmp_path, monkeypatch, finish):
    install_live(monkeypatch, finish=finish, usage={"prompt_tokens": 30, "completion_tokens": 4})
    output = tmp_path / "unknown-finish"
    result = asyncio.run(runner().run_diagnostic(source, output, mode="single", live=True))
    call = json.loads((output / "calls.json").read_text())[0]
    assert result["status"] == "invalid_response"
    assert call["finish_reason_known"] is False
    assert "DO_NOT_PERSIST_CREDENTIAL" not in "".join(p.read_text() for p in output.iterdir())
    assert call["usage"]["prompt_tokens"] == 30
    assert call["budget"]["llm_transport_attempts"] == 1


@pytest.mark.parametrize("target", ["inputs.json", "tool", "packages"])
def test_source_and_code_drift_during_model_call_blocks_completion(
    source, tmp_path, monkeypatch, target
):
    module = runner()
    if target == "tool":
        tool = tmp_path / "tool.py"
        tool.write_text("old")
        monkeypatch.setattr(module, "TOOL_PATH", tool)

    def mutate(_):
        path = (
            source / "inputs.json"
            if target == "inputs.json"
            else tool
            if target == "tool"
            else module.ROOT / "backend/packages/a.py"
        )
        path.write_text(path.read_text() + "\nchanged")

    install_live(monkeypatch, callback=mutate)
    result = asyncio.run(
        module.run_diagnostic(source, tmp_path / "drift", mode="single", live=True)
    )
    assert result["status"] == "blocked"
    assert result["integrity"]["unchanged"] is False


def test_http_guard_allows_only_exact_completion_post_and_rejects_redirect(monkeypatch):
    module = runner()

    async def send(self, request, **kwargs):
        return httpx.Response(302, request=request, headers={"location": "https://other.test"})

    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    async def attempt():
        with module.completion_boundary("https://api.test/v1/chat/completions"):
            async with httpx.AsyncClient() as client:
                for method, url in [
                    ("GET", "https://api.test/v1/chat/completions"),
                    ("POST", "https://other.test"),
                    ("POST", "https://api.test/v1/chat/completions"),
                ]:
                    with pytest.raises(ValueError):
                        await client.request(method, url)

    asyncio.run(attempt())


def test_cli_failure_is_saved_and_nonzero(source, tmp_path, capsys):
    value = json.loads((source / "inputs.json").read_text())
    value[0]["gold"] = "forbidden"
    write(source / "inputs.json", value)
    output = tmp_path / "failure"
    code = asyncio.run(
        runner().main(["--source-run", str(source), "--output", str(output), "--mode", "single"])
    )
    assert code != 0
    assert json.loads((output / "summary.json").read_text())["status"] == "blocked"
    assert json.loads(capsys.readouterr().out)["llm_transport_attempts"] == 0
