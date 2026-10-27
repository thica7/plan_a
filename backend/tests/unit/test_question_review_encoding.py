"""Lossless bounded v5 review transport and question-local eligibility.

Historical public candidates are transport-shape data only. Their saved labels
are never proof of a verified historical model input or current eligibility.
"""

import importlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_writer_question_delivery import service_for

from packages.agents.qa.evidence_alignment import audit_dimension_claims
from packages.research.question_scope import research_questions
from packages.schema.api_dto import RunDetail

ROOT = Path(__file__).resolve().parents[3]


def codec():
    name = "packages.agents.qa.question_review_encoding"
    assert importlib.util.find_spec(name), "A production lossless v5 codec is required"
    return importlib.import_module(name)


def archive(product):
    path = (
        ROOT
        / "data/artifacts/question-pool-atomic-2026-10-26"
        / f"live-{product}-verified/execution/run.json"
    )
    if not path.is_file():
        pytest.skip("Optional historical execution is not available in a clean checkout")
    detail = RunDetail.model_validate_json(path.read_text())
    service, record = service_for(detail, task_execution=True)
    return service, record, service._final_qa_snapshot(record)


def synthetic_case():
    """A complete factual A plus a separate, genuinely missing B original."""
    from dataclasses import replace

    from test_question_context_qa import case

    from packages.agents.writer.answer_coverage import parse_answer_coverage, unverified_coverage
    from packages.agents.writer.dimension_writer import render_dimension_report

    service, record, snapshot = case(factual=True, missing_for="clarification")
    service._settings = replace(service._settings, writer_task_execution_enabled=True)
    detail = record.detail
    audit = detail.report_dimension_audits[0]
    questions = research_questions(detail, audit.competitor, audit.dimension)
    claims = [row.claim.model_dump(mode="json") for row in audit.claims]
    ids = [claim["id"] for claim in claims]
    answers = parse_answer_coverage(
        json.dumps(
            dict(
                version=3,
                answers=[
                    dict(
                        question_id=questions[0]["question_id"],
                        status="answered",
                        resolution="direct",
                        conclusion="no",
                        claim_ids=ids,
                        missing_fields=[],
                        reason="The exact upper bound.",
                        subquestions=[
                            dict(
                                question_quote=questions[0]["question"],
                                claim_ids=ids,
                                conclusion="no",
                                relation="upper_bound",
                            )
                        ],
                    )
                ],
            )
        ),
        questions[:1],
        set(ids),
        claims=claims,
        required_binding_version=3,
        facts=snapshot.facts,
        require_subquestions=True,
    )
    assert answers[0].status == "answered"
    audit = audit.model_copy(
        update=dict(
            answer_coverage=(
                *answers,
                *unverified_coverage(questions[1:], "B original unavailable"),
            ),
            answer_review_contract="subquestion-premises-v1",
        )
    )
    detail.report_dimension_audits = [audit]
    detail.report_md = render_dimension_report(detail, [audit], snapshot=snapshot)
    service._record_evidence_artifact(
        record,
        kind="writer",
        uses=detail.evidence_consumptions,
        payload=service._writer_evidence_artifact_payload(detail),
    )
    return service, record, snapshot


def test_codec_roundtrip_canonical_and_true_net_savings():
    module = codec()
    rule = {
        "quote": "Only invited members may edit before removal unless restored AND logged in. " * 5,
        "conditions": {"a": True, "b": [1, None, False]},
        "coordinates": [0, 375],
    }
    value = {
        "version": 1,
        "basis_hash": "b" * 64,
        "findings": [
            {"claims": [rule, deepcopy(rule)], "answer": deepcopy(rule), "visible": rule["quote"]}
        ],
    }
    wire = module.encode(value)
    assert module.decode(wire) == value
    assert module.dumps(value) == module.dumps(dict(reversed(list(value.items()))))
    assert len(module.dumps(value).encode()) < len(json.dumps(value).encode())
    assert module.loads(module.dumps(value), expected=value) == value


@pytest.mark.parametrize("product", ["bitwarden", "1password"])
def test_complete_historical_shape_fits_without_dropping_any_claim(product):
    module = codec()
    fixtures = json.loads(
        (ROOT / "backend/tests/fixtures/final_question_v5_candidates.json").read_text()
    )
    longest = fixtures[product]
    payload = dict(version=1, basis_hash="b" * 64, findings=[longest])
    assert len(("\nJSON:\n" + module.dumps(payload)).encode()) <= 6000
    assert module.loads(module.dumps(payload), expected=payload) == payload


@pytest.mark.parametrize("change", ["missing", "cycle", "unused", "type", "version", "extra"])
def test_invalid_tables_and_ref_type_disguises_are_rejected(change):
    module = codec()
    wire = {"c": 1, "p": {"": 0}, "t": ["complete original " * 50]}
    if change == "missing":
        wire["p"][""] = 2
    elif change == "cycle":
        wire["t"][0] = {"": 0}
    elif change == "unused":
        wire["t"].append("unused")
    elif change == "type":
        wire["p"][""] = True
    elif change == "version":
        wire["c"] = 2
    else:
        wire["extra"] = []
    with pytest.raises(ValueError):
        module.decode(wire)


def test_expected_closure_rejects_other_package_and_condition_coordinate_changes():
    module = codec()
    expected = dict(basis_hash="original", claim=dict(quote="unless A AND B", start=4, end=18))
    for other in [
        dict(expected, basis_hash="foreign"),
        dict(expected, claim=dict(expected["claim"], start=5)),
        dict(expected, claim=dict(expected["claim"], quote="unless A OR B")),
    ]:
        with pytest.raises(ValueError):
            module.loads(module.dumps(other), expected=expected)
    with pytest.raises(ValueError):
        module.loads('{"c":1,"c":1,"p":{},"t":[]}', expected={})


def test_reserved_literal_objects_are_not_misread_as_references():
    module = codec()
    value = {"": 0, "nested": [{"": False}, {"": [["x", 1]]}], "text": "preserved"}
    assert module.loads(module.dumps(value), expected=value) == value


@pytest.mark.asyncio
async def test_attributable_sibling_coverage_gap_does_not_make_complete_question_diagnostic(
    monkeypatch,
):
    from test_final_question_reconciliation import reviewed
    from test_independent_final_question_qa import payload_from, traced_model_double

    from packages.agents.qa.question_reconciliation import reconcile_question_findings

    service, record, snapshot = synthetic_case()
    assert service._final_qa_producer_verified(record, snapshot)
    evidence = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert {issue.metadata["claim_audit_reason"] for issue in evidence} == {
        "answer_coverage_incomplete"
    }
    seen = []

    async def model(record, **kwargs):
        payload = payload_from(kwargs)
        seen.extend(payload["findings"])
        return reviewed(payload)

    traced_model_double(monkeypatch, service, model)
    await reconcile_question_findings(service, record, [], evidence_issues=evidence)
    rows = {row["question_id"]: row for row in seen}
    answers = record.detail.report_dimension_audits[0].answer_coverage
    assert rows[answers[0].question_id]["diagnostic_only"] is False
    assert rows[answers[1].question_id]["diagnostic_only"] is True


def test_forged_coverage_metadata_and_rehashed_id_cannot_hide_an_unknown_issue():
    from packages.agents.qa.independent_question_review import _question_verified

    service, record, snapshot = synthetic_case()
    original = audit_dimension_claims(service, record, snapshot, producer_verified=True)[0]
    audit = record.detail.report_dimension_audits[0]
    question = research_questions(record.detail, audit.competitor, audit.dimension)[0]
    forged = original.model_copy(
        update={
            "problem": "Canonical source identity is unknown; fake coverage metadata.",
        }
    )
    assert not _question_verified(
        service, record, snapshot, question, audit, [forged], producer_verified=True
    )


@pytest.mark.asyncio
async def test_optional_archived_cloudflare_isolated_by_actual_dispatch(monkeypatch):
    from test_final_question_reconciliation import reviewed
    from test_independent_final_question_qa import payload_from, traced_model_double

    from packages.agents.qa.question_reconciliation import reconcile_question_findings

    service, record, snapshot = archive("cloudflare")
    evidence = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    seen = []

    async def model(record, **kwargs):
        payload = payload_from(kwargs)
        seen.extend(payload["findings"])
        return reviewed(payload)

    traced_model_double(monkeypatch, service, model)
    await reconcile_question_findings(service, record, [], evidence_issues=evidence)
    assert [row["diagnostic_only"] for row in seen] == [False, True]


@pytest.mark.parametrize(
    "kind",
    [
        "unknown",
        "unknown_source",
        "canonical",
        "canonical_unselected",
        "producer",
        "id",
        "snapshot",
        "scope",
    ],
)
def test_hard_issue_identity_and_producer_guards_still_block_complete_a(kind):
    from packages.agents.qa.independent_question_review import _question_verified

    service, record, snapshot = synthetic_case()
    audit = record.detail.report_dimension_audits[0]
    question = research_questions(record.detail, audit.competitor, audit.dimension)[0]
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    if kind == "unknown":
        issues = [object()]
    elif kind in {"canonical", "canonical_unselected", "unknown_source"}:
        source = next(s for s in snapshot.sources if s.id == audit.claims[0].claim.source_ids[0])
        if kind in {"canonical_unselected", "unknown_source"}:
            source = next(
                s for s in snapshot.sources if s.id not in audit.claims[0].claim.source_ids
            )
        reason = (
            "unknown_future_reason"
            if kind == "unknown_source"
            else "canonical_document_unavailable"
        )
        issues = [
            issues[0].model_copy(
                update=dict(
                    id="qa-evidence-"
                    + service._evidence_artifact_hash([snapshot.id, source.id, reason])[:24],
                    target_agent="collector",
                    field_path=f"report.citations.{source.id}",
                    metadata=dict(
                        evidence_reason=reason,
                        snapshot_id=snapshot.id,
                        source_ids=[source.id],
                        fact_ids=[f.id for f in snapshot.facts if f.source_id == source.id],
                        document_id=source.document_id,
                        unpublishable_evidence=True,
                    ),
                )
            )
        ]
    elif kind == "id":
        issues = [issues[0].model_copy(update=dict(id="forged-coverage"))]
    elif kind == "snapshot":
        issues = [
            issues[0].model_copy(
                update=dict(metadata={**issues[0].metadata, "snapshot_id": "foreign"})
            )
        ]
    elif kind == "scope":
        issues = [issues[0].model_copy(update=dict(target_competitor="Different Product"))]
    assert not _question_verified(
        service, record, snapshot, question, audit, issues, producer_verified=kind != "producer"
    )


def test_irreducible_long_context_is_wholly_unsent_and_reserve_stays_bounded():
    import hashlib

    from packages.agents.qa.independent_question_review import (
        FINAL_QA_REQUEST_RESERVE,
        INDEPENDENT_SYSTEM,
        MAX_REVIEW_OUTPUT_TOKENS,
        TASK_REVIEW_BYTES,
    )

    text = "".join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(150))
    row = dict(issue_id="whole", claims=[dict(quote=text, start=0, end=len(text))])
    packed, omitted = codec().final_review_batches([row], "basis", max_bytes=6000, max_batches=6)
    assert packed == [] and omitted == ["whole"]
    assert len(row["claims"][0]["quote"]) == len(text)
    # The historical codec still has its 6000-byte limit above. Current v6
    # protects the readable 8192-byte request plus its actual system and output.
    assert TASK_REVIEW_BYTES == 8192 and MAX_REVIEW_OUTPUT_TOKENS == 1600
    assert FINAL_QA_REQUEST_RESERVE == len(INDEPENDENT_SYSTEM.encode()) + 14000 + 256 + 1600 + 2


@pytest.mark.asyncio
async def test_atomic_core_sent_only_to_other_qid_cannot_close_current_qid(monkeypatch):
    from dataclasses import replace

    from claim_review_fixture import answer_response, expand_prompt_payload
    from test_question_atomic_delivery import TEXTS, atomic_case, atomic_model
    from test_task_support_selection import append_response

    from packages.agents.qa.question_context import question_delivery_complete
    from packages.agents.writer import question_atomic_delivery as atomic

    setup = await atomic_case(
        TEXTS[:1],
        question=(
            "Example Product：访客有私人区域吗？\nExample Product：来宾账户能拥有私人区域吗？"
        ),
    )
    service, record, snapshot, *_ = setup
    service._settings = replace(service._settings, writer_question_atomic_enabled=True)
    normal = atomic_model(service, {})

    async def writer(record, **kwargs):
        if kwargs["name"] != atomic.ANSWER_NAME:
            return await normal(record, **kwargs)
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        local = {
            row["question_id"]: row["claim_ids"] for row in payload["question_claim_whitelist"]
        }
        response = answer_response(
            payload,
            dict(
                version=3,
                answers=[
                    dict(
                        question_id=q["question_id"],
                        status="answered",
                        resolution="direct",
                        conclusion="no",
                        claim_ids=local[q["question_id"]],
                        missing_fields=[],
                        reason="The exact guest restriction directly denies the request.",
                    )
                    for q in payload["questions"]
                ],
            ),
            relation="explicit_negative",
        )
        return append_response(service, record, kwargs, response)

    monkeypatch.setattr(service, "_trace_llm_text", writer)
    await service._real_writer_step(record)
    audit = record.detail.report_dimension_audits[0]
    questions = research_questions(record.detail, audit.competitor, audit.dimension)
    assert len(questions) == 2
    assert service._final_qa_producer_verified(record, snapshot)
    from packages.research.evidence.views import select_evidence_view

    use = next(u for u in record.detail.evidence_consumptions if u.id == audit.consumption_id)
    view = select_evidence_view(
        snapshot,
        agent="writer",
        competitor=use.competitor,
        dimension=use.dimension,
        fact_ids=use.requested_fact_ids,
        source_ids=use.requested_source_ids,
        max_bytes=use.view_max_bytes or use.max_bytes,
    )
    atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    assert question_delivery_complete(service, record.detail, snapshot, audit, questions[0])
    actual_replay = atomic.replay_atomic_delivery

    def only_other_question(*args, **kwargs):
        replay = actual_replay(
            *args, **kwargs
        )  # All original transport/binding validation still runs.
        assert replay["facts_by_question"][questions[1]["question_id"]]
        assert replay["facts"]  # The old union remains complete and cannot authorize q0.
        return {
            **replay,
            "facts_by_question": {**replay["facts_by_question"], questions[0]["question_id"]: []},
        }

    monkeypatch.setattr(atomic, "replay_atomic_delivery", only_other_question)
    assert not question_delivery_complete(service, record.detail, snapshot, audit, questions[0])
    assert question_delivery_complete(service, record.detail, snapshot, audit, questions[1])


def test_peer_audit_actual_hard_claim_failure_blocks_complete_a():
    from packages.agents.qa.independent_question_review import _question_verified
    from packages.agents.writer.dimension_writer import render_dimension_report

    service, record, snapshot = synthetic_case()
    detail = record.detail
    audit = detail.report_dimension_audits[0]
    peer = audit.model_copy(
        update=dict(
            competitor="Peer Product", consumption_id=None, claims=(), answer_coverage=(), gaps=()
        )
    )
    detail.report_dimension_audits = [audit, peer]
    detail.report_md = render_dimension_report(detail, [audit, peer], snapshot=snapshot)
    service._record_evidence_artifact(
        record,
        kind="writer",
        uses=detail.evidence_consumptions,
        payload=service._writer_evidence_artifact_payload(detail),
    )
    assert service._final_qa_producer_verified(record, snapshot)
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    peer_hard = [
        issue
        for issue in issues
        if issue.target_competitor == peer.competitor
        and issue.metadata["claim_audit_reason"] != "answer_coverage_incomplete"
    ]
    assert {issue.metadata["claim_audit_reason"] for issue in peer_hard} == {
        "claim_generation_view_missing",
        "claim_producer_unverified",
    }
    question = research_questions(detail, audit.competitor, audit.dimension)[0]
    assert not _question_verified(
        service, record, snapshot, question, audit, peer_hard, producer_verified=True
    )
