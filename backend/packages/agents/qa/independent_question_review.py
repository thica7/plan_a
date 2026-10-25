"""Bounded final QA of current questions, independent of Reflector availability."""

from __future__ import annotations

import asyncio
import json

import httpx

from packages.agents.qa.question_reconciliation import (
    MAX_FINDINGS,
    RECEIPT_NAME,
    SYSTEM,
    TASK_REVIEW_BYTES,
    _answer_support,
    _basis,
    _Decision,
    _question_id,
    _review_response,
    _structural_or_mixed,
    final_review_batches,
)
from packages.agents.writer.answer_presentation import audit_heading, question_coverage_matches
from packages.agents.writer.task_answers import reviewed_task_answer_rows
from packages.llm.errors import LLMExecutionLimitError
from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.research.evidence.snapshot_models import canonical_json
from packages.research.question_scope import question_request_context, research_questions
from packages.schema.decision_brief import safe_decision_brief_text
from packages.schema.models import QCIssue, RedoScope

MAX_ATTEMPTS_PER_FINDING = 2
MAX_REVIEW_BATCHES = 6
PROTOCOL = "independent_questions_v3"
INDEPENDENT_SYSTEM = SYSTEM + (
    " Audit EVERY independent_question_check against every request and shared premise in the "
    "complete original question and bound request_context, even without a historical objection. "
    "Roles, plans, settings and other scenario conditions explicitly GIVEN in the request or "
    "its bound parent are hypothetical inputs: do NOT demand source evidence proving those "
    "assumptions. Every product rule used in the answer still needs complete selected source "
    "support, preserving its conditions and exceptions. A supported rule plus those given "
    "assumptions may establish a bounded logical inference. Permission does not imply an "
    "obligation; authorization for one resource does not imply authorization for another. "
    "These logical non-entailments need no separate explicit negative product quote, but "
    "do not invent runtime rejection, enforcement or broader product behavior. "
    "visible_answer is the actual "
    "local publication; answer metadata proves no publication. Check omitted branches, unsupported "
    "premises and exact selected sources. Only a fully answered independent check may set "
    "finding_fully_addressed=true and superseded; otherwise use keep and enumerate remaining_gaps. "
    "Diagnostic checks cannot approve a question or clear historical issues. "
    "Resolve each historical objection in full. Echo only batch IDs. "
    "Copy expected_claim_ids EXACTLY to claim_ids, including "
    "[]. They identify the whole answer. Inspect task_support_claim_ids as visible local support; "
    "never replace expected_claim_ids or promote local conclusions to complete coverage."
    " Parent requests resolve shared actors, roles, plans, prerequisites; they cannot supply "
    "unsupported product assertions."
)
MAX_REVIEW_OUTPUT_TOKENS = 1600
FINAL_QA_REQUEST_RESERVE = (
    len(INDEPENDENT_SYSTEM.encode()) + TASK_REVIEW_BYTES + 256 + MAX_REVIEW_OUTPUT_TOKENS + 2
)


def _visible_answer(detail, audit, question):
    """Read the actual local publication, including a changed or absent answer."""
    lines = detail.report_md.splitlines()
    headings = [
        i for i, line in enumerate(lines) if line == audit_heading(audit, detail.output_language)
    ]
    if len(headings) != 1:
        return ""
    start = headings[0] + 1
    end = next(
        (i for i in range(start, len(lines)) if lines[i].startswith(("# ", "## ", "### "))),
        len(lines),
    )
    prefix = "- " + safe_decision_brief_text(question["question"]) + " — "
    starts = [i for i in range(start, end) if lines[i].startswith(prefix)]
    if len(starts) != 1:
        return ""
    start = starts[0]
    end = next((i for i in range(start + 1, end) if lines[i].startswith(("- ", "#### "))), end)
    return "\n".join(lines[start:end]).rstrip()


def _question_context(service, record, snapshot, question, audit, *, verified):
    detail = record.detail
    qid = question["question_id"]
    answers = [answer for answer in audit.answer_coverage if answer.question_id == qid]
    answer = answers[0] if len(answers) == 1 else None
    matches = bool(answer) and question_coverage_matches(
        detail.report_md,
        audit,
        detail.output_language,
        audits=detail.report_dimension_audits,
        detail=detail,
    )
    support = _answer_support(detail, snapshot, audit, answer, question) if answer else None
    tasks = (
        [row for row in reviewed_task_answer_rows(detail, audit) if row["question_id"] == qid]
        if matches
        else []
    )
    selected_ids = set(answer.claim_ids) if answer else set()
    selected_ids.update(row["claim_id"] for row in tasks)
    claims = [
        row.claim.model_dump(mode="json")
        for row in audit.claims
        if row.status == "supported" and row.claim.id in selected_ids
    ]
    return dict(
        question_id=qid,
        question=question["question"],
        request_context=question_request_context(
            detail, audit.competitor, audit.dimension, [question]),
        answer=answer.model_dump(mode="json")
        if answer
        else dict(
            question_id=qid, status="unverified", claim_ids=[], conclusion="unknown", answer=""
        ),
        visible_answer=_visible_answer(detail, audit, question),
        claims=claims,
        task_answers=[
            {k: v for k, v in row.items() if k not in {"claim", "question", "question_id"}}
            for row in tasks
        ],
        task_support_claim_ids=sorted({row["claim_id"] for row in tasks}),
        publication_matches=matches,
        support_verified=bool(verified and support is not None),
    )


def _valid_identity(review, candidate):
    return (
        review.question_id == candidate["question_id"]
        and review.support_digest == candidate["support_digest"]
        and len(review.claim_ids) == len(set(review.claim_ids))
        and set(review.claim_ids) == set(candidate["answer"]["claim_ids"])
    )


def _affirmative(review, candidate):
    if (
        review is None
        or candidate["diagnostic_only"]
        or not review.finding_fully_addressed
        or review.remaining_gaps
    ):
        return False
    resolution = candidate["answer"].get("resolution")
    return (review.disposition == "superseded" and resolution in {"direct", "conditional"}) or (
        review.disposition == "current_limitation"
        and resolution in {"insufficient", "clarification"}
    )


def _is_timeout(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
            return True
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return False


def _cache(detail, basis_hash, candidates):
    cached = next(
        (
            span
            for span in reversed(detail.trace_spans)
            if span.name == RECEIPT_NAME
            and span.metadata.get("basis_hash") == basis_hash
            and span.full_output
        ),
        None,
    )
    if cached is None:
        return {}, {}, set(), set(), []
    try:
        receipt = json.loads(cached.full_output)
        if receipt.get("mode") != PROTOCOL:
            return {}, {}, set(), set(), []
        attempts = {
            key: max(0, int(value))
            for key, value in receipt.get("attempts_by_issue_id", {}).items()
            if key in candidates
        }
        reviews = {}
        for row in (receipt.get("model_review") or {}).get("reviews", []):
            review = _Decision.model_validate(row)
            if review.issue_id in candidates and _valid_identity(
                review, candidates[review.issue_id]
            ):
                reviews[review.issue_id] = review
        return (
            reviews,
            attempts,
            set(receipt.get("sent_issue_ids", [])) & candidates.keys(),
            set(receipt.get("timeout_issue_ids", [])) & candidates.keys(),
            receipt.get("batch_receipts", []),
        )
    except (ValueError, TypeError, KeyError):
        return {}, {}, set(), set(), []


def _question_issue(candidate, review, basis_hash, pending_reason):
    gaps = review.remaining_gaps if review else []
    reason = "; ".join(gaps) or (review.reason if review else pending_reason)
    if candidate["diagnostic_only"]:
        reason = "当前正文或所选支持尚未通过发布资格核验。 " + reason
    return QCIssue(
        id=candidate["issue_id"],
        severity="blocker",
        detected_by="coverage",
        target_agent="writer",
        target_subagent=candidate["dimension"],
        target_competitor=candidate["competitor"],
        field_path="report_dimension_audits.answer_coverage",
        problem=f"{candidate['question_id']}: {reason}",
        redo_scope=RedoScope(
            kind="writer_only",
            target_subagent=candidate["dimension"],
            target_competitor=candidate["competitor"],
            rationale="独立最终逐题审核保留未完成项。",
        ),
        metadata=dict(
            issue_kind="independent_final_question",
            question_id=candidate["question_id"],
            basis_hash=basis_hash,
            final_question_disposition=review.model_dump(mode="json") if review else None,
        ),
    )


async def review_current_questions(service, record, issues, *, evidence_issues):
    """Advance bounded complete windows; paid retries follow unseen findings."""
    detail = record.detail
    snapshot = service._final_qa_snapshot(record)
    dependency_hash = _basis(service, record, snapshot)
    writer_hash = service._evidence_artifact_hash(service._writer_evidence_artifact_payload(detail))
    verified = not evidence_issues and service._final_qa_producer_verified(record, snapshot)
    questions = {}
    for audit in detail.report_dimension_audits:
        for question in research_questions(detail, audit.competitor, audit.dimension):
            questions.setdefault(question["question_id"], (question, audit))
    contexts = {
        qid: _question_context(service, record, snapshot, question, audit, verified=verified)
        for qid, (question, audit) in questions.items()
    }
    candidates = []
    historical = [issue for issue in issues if issue.detected_by == "reflector"]
    for qid, (_, audit) in questions.items():
        context = contexts[qid]
        candidates.append(
            dict(
                **context,
                issue_id=f"final-question-{qid}",
                finding=(
                    "Independently check every request and premise of the complete "
                    "original question."
                ),
                independent_question_check=True,
                diagnostic_only=not context["support_verified"],
                competitor=audit.competitor,
                dimension=audit.dimension,
            )
        )
    for issue in historical[:MAX_FINDINGS]:
        qid = _question_id(issue, questions)
        context = contexts.get(
            qid,
            dict(
                question_id="unmapped",
                question="Unmapped finding",
                answer=dict(claim_ids=[], status="unverified", answer=""),
                claims=[],
                visible_answer="",
                support_verified=False,
            ),
        )
        candidates.append(
            dict(
                **context,
                issue_id=issue.id,
                finding=issue.problem,
                diagnostic_only=not context["support_verified"] or _structural_or_mixed(issue),
            )
        )
    for candidate in candidates:
        candidate["expected_claim_ids"] = list(candidate["answer"]["claim_ids"])
        candidate["support_digest"] = service._evidence_artifact_hash(candidate)
    basis_hash = service._evidence_artifact_hash(
        dict(dependencies=dependency_hash, protocol=PROTOCOL, candidates=candidates)
    )
    by_id = {row["issue_id"]: row for row in candidates}
    reviews, attempts, sent, timeouts, batch_receipts = _cache(detail, basis_hash, by_id)
    pending = [
        row
        for row in candidates
        if row["issue_id"] not in reviews
        and attempts.get(row["issue_id"], 0) < MAX_ATTEMPTS_PER_FINDING
    ]
    pending.sort(
        key=lambda row: (
            not row.get("independent_question_check", False),
            attempts.get(row["issue_id"], 0) > 0,
        )
    )
    batches, omitted = final_review_batches(
        pending, basis_hash, max_bytes=TASK_REVIEW_BYTES, max_batches=MAX_REVIEW_BATCHES
    )
    if batches:
        budget = service._run_llm_budget(record)
        budget.delivery_finished.discard("final_qa:run")
        service._checkpoint_llm_budget(record, budget)
    cancellation = None
    for batch in batches:
        ids = {row["issue_id"] for row in batch["findings"]}
        claims = [claim for key in ids for claim in by_id[key]["claims"]]
        fact_ids = sorted({fid for claim in claims for fid in claim["fact_ids"]})
        source_ids = sorted({sid for claim in claims for sid in claim["source_ids"]})
        batch_status, was_sent, valid_ids, reason = "unsent", False, [], ""
        before = len(detail.trace_spans)
        try:
            view, use = service._begin_evidence_use(
                record, agent="qa", fact_ids=fact_ids, source_ids=source_ids
            )
            user = "\nJSON:\n" + canonical_json(batch)
            if len(user.encode()) > min(TASK_REVIEW_BYTES, use.max_bytes) or not set(
                fact_ids
            ) <= set(view.fact_ids):
                raise ValueError("Complete final question context does not fit the evidence view")
            service._validate_evidence_use(record, use)
            was_sent = True
            response = await service._trace_llm_text(
                record,
                agent="qa",
                subagent=None,
                name="final_question_reconciliation",
                system=INDEPENDENT_SYSTEM,
                user=user,
                max_output_tokens=MAX_REVIEW_OUTPUT_TOKENS,
                max_request_attempts=min(
                    MAX_ATTEMPTS_PER_FINDING - attempts.get(key, 0) for key in ids
                ),
                timeout_seconds=service._settings.llm_timeout_seconds,
            )
            service._validate_evidence_use(record, use)
            parsed = _review_response(response, basis_hash)
            if not {row.issue_id for row in parsed.reviews} <= ids:
                raise ValueError("Final QA batch returned foreign findings")
            for review in parsed.reviews:
                if _valid_identity(review, by_id[review.issue_id]):
                    reviews[review.issue_id] = review
                    valid_ids.append(review.issue_id)
            batch_status = "valid" if set(valid_ids) == ids else "partial"
        except EvidenceUseRejectedError:
            raise
        except LLMExecutionLimitError as exc:
            was_sent = False
            reason = f"Final QA not sent: {exc}."
        except (TimeoutError, asyncio.CancelledError) as exc:
            batch_status = "timeout"
            reason = "Final QA timed out; question review remains pending."
            if isinstance(exc, asyncio.CancelledError):
                cancellation = exc
        except Exception as exc:
            batch_status = "timeout" if _is_timeout(exc) else "invalid" if was_sent else "unsent"
            failure = "response invalid" if was_sent else "context unavailable"
            reason = (
                "Final QA timed out; question review remains pending."
                if batch_status == "timeout"
                else f"Final QA {failure}: {type(exc).__name__}."
            )
        spans = [
            span
            for span in detail.trace_spans[before:]
            if span.name == "final_question_reconciliation" and span.kind == "llm"
        ]
        if spans:
            was_sent = any(span.metadata.get("llm_transport_attempts", 0) for span in spans)
        timeout_attempts = sum(int(span.metadata.get("llm_timeout_attempts", 0)) for span in spans)
        if was_sent:
            if batch_status == "unsent":
                batch_status = "unavailable"
                reason = "Final QA request attempts exhausted; review remains incomplete."
            sent.update(ids)
            attempted = (
                sum(int(span.metadata.get("llm_request_attempts", 0)) for span in spans) or 1
            )
            for key in ids:
                attempts[key] = attempts.get(key, 0) + attempted
            if timeout_attempts or batch_status == "timeout":
                timeouts.update(ids)
        else:
            batch_status = "unsent"
            for key in valid_ids:
                reviews.pop(key, None)
            valid_ids = []
        if batch_status == "partial":
            reason = (
                "Final QA response omitted or invalidated this finding; review remains pending."
            )
        batch_receipts.append(
            dict(
                issue_ids=sorted(ids),
                status=batch_status,
                sent=was_sent,
                valid_review_issue_ids=sorted(valid_ids),
                timeout_attempts=timeout_attempts or int(batch_status == "timeout"),
                reason=reason,
            )
        )
        if cancellation:
            break
    if (
        dependency_hash != _basis(service, record, service._final_qa_snapshot(record))
        or verified
        and not service._final_qa_producer_verified(record, snapshot)
    ):
        raise EvidenceUseRejectedError(
            "Final question review dependencies changed during reconciliation"
        )
    valid = set(reviews)
    planned = list(by_id)
    unresolved = [key for key in planned if key not in valid]
    unreviewed_reasons = {}
    for key in unresolved:
        if key in omitted:
            _, single_omitted = final_review_batches(
                [by_id[key]], basis_hash, max_bytes=TASK_REVIEW_BYTES, max_batches=1
            )
            reason = (
                "Complete question context exceeded the bounded final QA byte limit."
                if single_omitted
                else "Complete question context is pending beyond the bounded review window."
            )
        elif attempts.get(key, 0) >= MAX_ATTEMPTS_PER_FINDING:
            reason = "Final QA attempt limit reached; review remains incomplete."
        else:
            reason = next(
                (
                    batch.get("reason")
                    for batch in reversed(batch_receipts)
                    if key in batch["issue_ids"] and batch.get("reason")
                ),
                "Final QA review remains pending.",
            )
        unreviewed_reasons[key] = reason
    decisions = {}
    for issue in historical:
        candidate, review = by_id.get(issue.id), reviews.get(issue.id)
        if candidate and _affirmative(review, candidate):
            decisions[issue.id] = review
    question_candidates = [row for row in candidates if row.get("independent_question_check")]
    resumable = [
        key
        for key in unresolved
        if attempts.get(key, 0) < MAX_ATTEMPTS_PER_FINDING
        and not final_review_batches(
            [by_id[key]], basis_hash, max_bytes=TASK_REVIEW_BYTES, max_batches=1
        )[1]
    ]
    passed = {
        row["issue_id"]
        for row in question_candidates
        if _affirmative(reviews.get(row["issue_id"]), row)
    }
    receipt = dict(
        version=1,
        mode=PROTOCOL,
        basis_hash=basis_hash,
        snapshot_id=snapshot.id,
        snapshot_hash=snapshot.content_hash,
        writer_payload_hash=writer_hash,
        reviews=[
            decisions[issue.id].model_dump(mode="json")
            if issue.id in decisions
            else dict(
                issue_id=issue.id,
                disposition="keep",
                reason="No eligible affirmative historical review.",
            )
            for issue in historical
        ],
        model_review=dict(
            version=1,
            basis_hash=basis_hash,
            reviews=[reviews[key].model_dump(mode="json") for key in planned if key in valid],
        )
        if reviews
        else None,
        model_execution="not_requested"
        if not planned
        else "completed"
        if not unresolved
        else "partial"
        if valid
        else "unavailable"
        if sent
        else "not_requested",
        planned_batches=len(batches),
        review_batch_limit=MAX_REVIEW_BATCHES,
        resumable_issue_ids=resumable,
        planned_issue_ids=planned,
        sent_issue_ids=[key for key in planned if key in sent],
        valid_review_issue_ids=[key for key in planned if key in valid],
        timeout_issue_ids=[key for key in planned if key in timeouts],
        unresolved_timeout_issue_ids=[
            key for key in planned if key in timeouts and key not in valid
        ],
        unsent_issue_ids=[key for key in planned if key not in sent],
        omitted_issue_ids=omitted,
        attempts_by_issue_id={key: attempts.get(key, 0) for key in planned},
        unreviewed_reasons=unreviewed_reasons,
        passed_question_ids=[
            row["question_id"] for row in question_candidates if row["issue_id"] in passed
        ],
        blocked_question_ids=[
            row["question_id"] for row in question_candidates if row["issue_id"] not in passed
        ],
        question_review_states={
            row["question_id"]: (
                reviews[row["issue_id"]].disposition
                if row["issue_id"] in passed
                else "blocked"
                if row["issue_id"] in valid
                else "pending"
            )
            for row in question_candidates
        },
        model_reviewed_issue_ids=[key for key in planned if key in valid],
        model_unreviewed_issue_ids=unresolved,
        retry_exhausted_issue_ids=[
            key for key in unresolved if attempts.get(key, 0) >= MAX_ATTEMPTS_PER_FINDING
        ],
        batch_receipts=batch_receipts,
    )
    service._trace_local_tool(
        record,
        agent="qa",
        subagent=None,
        name=RECEIPT_NAME,
        input_text=canonical_json(dict(version=1, basis_hash=basis_hash, findings=candidates)),
        output_text=canonical_json(receipt),
        metadata=dict(
            basis_hash=basis_hash, snapshot_id=snapshot.id, writer_payload_hash=writer_hash
        ),
    )
    result = []
    for issue in issues:
        if issue.metadata.get("issue_kind") == "independent_final_question":
            continue
        decision = decisions.get(issue.id)
        if decision and decision.disposition == "superseded":
            continue
        if decision and decision.disposition == "current_limitation":
            issue = issue.model_copy(
                update=dict(
                    severity="info",
                    problem="当前回答保留已列明的缺失条件，尚不能给出确定金额或结论。",
                    metadata={
                        **issue.metadata,
                        "historical_problem": issue.problem,
                        "final_question_disposition": decision.model_dump(mode="json"),
                        "basis_hash": basis_hash,
                    },
                )
            )
        result.append(issue)
    for candidate in candidates:
        if not candidate.get("independent_question_check"):
            continue
        review = reviews.get(candidate["issue_id"])
        if candidate["issue_id"] in passed:
            continue
        result.append(
            _question_issue(
                candidate,
                review,
                basis_hash,
                unreviewed_reasons.get(candidate["issue_id"], "最终逐题审核尚未取得合法完整返回。"),
            )
        )
    if not resumable:
        service._finish_delivery_phase(record, "final_qa", None)
    if cancellation:
        raise cancellation
    return result
