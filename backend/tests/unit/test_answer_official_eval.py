import asyncio
import hashlib
import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "backend/scripts/eval_answer_official.py"
URL = "https://help.miro.com/hc/en-us/articles/360012524559-Collaboration-with-Visitors"


def runner():
    assert SCRIPT.is_file(), "bounded answer diagnostic entry is missing"
    return importlib.import_module("scripts.eval_answer_official")


def fixture(tmp_path, count=2):
    rows = [
        {
            "id": f"new-{i}",
            "product": "Miro",
            "question": f"问题 {i}？",
            "review_status": "candidate",
            "reference_answer": "GOLD_ONLY",
            "expected_outcome": "answer",
            "required_conditions": ["GOLD_ONLY"],
            "sources": [
                {
                    "id": f"source-{i}",
                    "title": "Collaboration with Visitors",
                    "url": URL,
                    "excerpt": "GOLD_ONLY",
                    "nested": {"answer": "GOLD_ONLY"},
                }
            ],
        }
        for i in range(count)
    ]
    path = tmp_path / "cases.jsonl"
    save(path, rows)
    return path, rows


def save(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def test_runtime_allowlist_removes_gold_at_every_source_depth(tmp_path):
    path, _ = fixture(tmp_path)
    payloads, manifest = runner().prepare_inputs(path, mode="candidate-diagnostic")
    assert len(payloads) == 2
    assert "GOLD_ONLY" not in json.dumps(payloads)
    assert set(payloads[0]) == {"id", "product", "question", "sources"}
    assert set(payloads[0]["sources"][0]) == {"id", "title", "url"}
    assert manifest["semantic_quality"] == "pending_human"
    assert manifest["review_mode"] == "candidate-diagnostic"


def test_default_preview_has_no_runtime_or_network(tmp_path, monkeypatch, capsys):
    path, _ = fixture(tmp_path)
    module = runner()
    monkeypatch.setattr(module, "run_live", lambda *a, **kw: pytest.fail("runtime called"))
    asyncio.run(module.main(["--cases", str(path), "--mode", "candidate-diagnostic"]))
    preview = json.loads(capsys.readouterr().out)
    assert preview["mode"] == "preview"
    assert preview["fetch_attempts"] == preview["llm_transport_attempts"] == 0


@pytest.mark.parametrize("mode", [None, "formal", "candidate", "reviewed"])
def test_prepare_requires_one_explicit_supported_review_mode(tmp_path, mode):
    path, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match="mode"):
        runner().prepare_inputs(path, mode=mode)


def test_human_review_cannot_be_bypassed_by_selection(tmp_path):
    path, rows = fixture(tmp_path)
    rows[0].update(
        review_status="reviewed", reviewed_by="project_user", reviewed_at="2026-10-16T01:50:40Z"
    )
    save(path, rows)
    with pytest.raises(ValueError, match="human review"):
        runner().prepare_inputs(path, mode="human-reviewed", case_ids=["new-0"])
    rows[1].update(
        review_status="reviewed", reviewed_by="project_user", reviewed_at="2026-10-16T01:50:40Z"
    )
    save(path, rows)
    payloads, _ = runner().prepare_inputs(path, mode="human-reviewed", case_ids=["new-0"])
    assert len(payloads) == 1


def test_selection_supports_new_ids_and_keeps_scope_bounded(tmp_path):
    path, _ = fixture(tmp_path, 8)
    selected = ["new-6", "new-1", "new-3"]
    payloads, manifest = runner().prepare_inputs(
        path, mode="candidate-diagnostic", case_ids=selected
    )
    assert [row["id"] for row in payloads] == selected
    assert manifest["input_cases"] == 8
    with pytest.raises(ValueError, match="four"):
        runner().prepare_inputs(path, mode="candidate-diagnostic")
    with pytest.raises(ValueError, match="selection"):
        runner().prepare_inputs(path, mode="candidate-diagnostic", case_ids=["missing"])
    path, _ = fixture(tmp_path, 9)
    with pytest.raises(ValueError, match="eight"):
        runner().prepare_inputs(path, mode="candidate-diagnostic", case_ids=["new-0"])


def test_question_limit_rejects_instead_of_truncating(tmp_path):
    path, rows = fixture(tmp_path, 1)
    rows[0]["question"] = "问" * 501
    save(path, rows)
    with pytest.raises(ValueError, match="500"):
        runner().prepare_inputs(path, mode="candidate-diagnostic")


def test_runtime_question_keeps_product_and_counts_its_prefix(tmp_path):
    from scripts.eval_official_writer import runtime_questions

    path, rows = fixture(tmp_path, 1)
    assert runtime_questions(rows) == "Miro: 问题 0？"
    rows[0]["question"] = "问" * 499
    save(path, rows)
    with pytest.raises(ValueError, match="500"):
        runner().prepare_inputs(path, mode="candidate-diagnostic")


def test_manifest_freezes_actual_runtime_settings_dependency(tmp_path, monkeypatch):
    import shutil

    path, _ = fixture(tmp_path)
    module = runner()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in (
        "eval_answer_official.py",
        "eval_official_writer.py",
        "eval_evidence_binding.py",
        "eval_live_products.py",
        "export_agent_eval.py",
    ):
        shutil.copyfile(SCRIPT.with_name(name), scripts / name)
    monkeypatch.setattr(module, "__file__", str(scripts / SCRIPT.name))
    _, manifest = module.prepare_inputs(path, mode="candidate-diagnostic")
    helper = scripts / "eval_evidence_binding.py"
    helper.write_bytes(helper.read_bytes() + b"\n# runtime settings changed\n")
    with pytest.raises(ValueError, match="manifest.*drift"):
        module.prepare_inputs(
            path, mode="candidate-diagnostic", manifest_hash=manifest["manifest_sha256"]
        )


def test_unknown_or_changed_official_url_is_rejected(tmp_path):
    path, rows = fixture(tmp_path, 1)
    rows[0]["sources"][0]["url"] += "?unreviewed=1"
    save(path, rows)
    with pytest.raises(ValueError, match="registry"):
        runner().prepare_inputs(path, mode="candidate-diagnostic")


def test_frozen_input_registry_and_manifest_drift_abort(tmp_path):
    path, rows = fixture(tmp_path)
    module = runner()
    _, manifest = module.prepare_inputs(path, mode="candidate-diagnostic")
    with pytest.raises(ValueError, match="input.*drift"):
        module.prepare_inputs(path, mode="candidate-diagnostic", input_hash="0" * 64)
    with pytest.raises(ValueError, match="registry.*drift"):
        module.prepare_inputs(path, mode="candidate-diagnostic", registry_hash="0" * 64)
    with pytest.raises(ValueError, match="manifest.*drift"):
        module.prepare_inputs(path, mode="candidate-diagnostic", manifest_hash="0" * 64)
    selected, changed = module.prepare_inputs(path, mode="candidate-diagnostic", case_ids=["new-0"])
    assert changed["manifest_sha256"] != manifest["manifest_sha256"]
    assert len(selected) == 1


def test_manifest_freezes_runner_and_production_code(tmp_path, monkeypatch):
    path, _ = fixture(tmp_path)
    module = runner()
    package = tmp_path / "backend/packages"
    package.mkdir(parents=True)
    source = package / "sample.py"
    source.write_text("version = 1\n")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    _, manifest = module.prepare_inputs(path, mode="candidate-diagnostic")
    assert manifest["runner_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert len(manifest["official_runner_sha256"]) == len(manifest["production_code_sha256"]) == 64
    source.write_text("version = 2\n")
    with pytest.raises(ValueError, match="manifest.*drift"):
        module.prepare_inputs(
            path, mode="candidate-diagnostic", manifest_hash=manifest["manifest_sha256"]
        )


def test_run_requires_three_frozen_hashes_before_runtime(tmp_path, monkeypatch):
    path, _ = fixture(tmp_path)
    module = runner()
    monkeypatch.setattr(module, "run_live", lambda *a, **kw: pytest.fail("runtime called"))
    with pytest.raises(ValueError, match="three frozen"):
        asyncio.run(module.main(["--cases", str(path), "--mode", "candidate-diagnostic", "--run"]))


def test_drift_after_loading_is_detected(tmp_path, monkeypatch):
    path, _ = fixture(tmp_path)
    module = runner()
    original = module.runtime_payload

    def mutate(row):
        payload = original(row)
        path.write_bytes(path.read_bytes() + b"\n")
        return payload

    monkeypatch.setattr(module, "runtime_payload", mutate)
    with pytest.raises(ValueError, match="input.*drift"):
        module.prepare_inputs(path, mode="candidate-diagnostic")


def test_capture_only_dispatch_passes_only_sanitized_payload(tmp_path, monkeypatch, capsys):
    path, _ = fixture(tmp_path)
    module = runner()
    _, frozen = module.prepare_inputs(path, mode="candidate-diagnostic")
    calls = []

    async def capture(payloads, manifest, output, **kwargs):
        calls.append((deepcopy(payloads), manifest, kwargs))
        return {"status": "capture_only_test", "llm_transport_attempts": 0}

    monkeypatch.setattr(module, "run_live", capture)
    asyncio.run(
        module.main(
            [
                "--cases",
                str(path),
                "--mode",
                "candidate-diagnostic",
                "--run",
                "--capture-only",
                "--expected-input-sha256",
                frozen["input_sha256"],
                "--expected-registry-sha256",
                frozen["registry_sha256"],
                "--expected-manifest-sha256",
                frozen["manifest_sha256"],
                "--output",
                str(tmp_path / "capture"),
            ]
        )
    )
    assert len(calls) == 1 and calls[0][2]["capture_only"] is True
    assert "GOLD_ONLY" not in json.dumps(calls[0][0])
    assert json.loads(capsys.readouterr().out)["status"] == "capture_only_test"
