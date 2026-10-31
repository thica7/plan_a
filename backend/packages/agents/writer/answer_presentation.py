"""One deterministic presentation for final question answers and publication QA."""

from packages.research.question_scope import research_questions
from packages.schema.decision_brief import safe_decision_brief_text as plain


def observation_claims(detail, audit):
    """Explicit questions publish deductions only inside their final answer."""
    supported = tuple(item for item in audit.claims if item.status == "supported")
    if all(item.claim.kind == "fact" for item in supported):
        return supported
    has_questions = bool(
        audit.answer_coverage or research_questions(detail, audit.competitor, audit.dimension)
    )
    from packages.agents.writer.task_projection import projected_task_claim_ids

    projected = projected_task_claim_ids(detail, audit) if has_questions else set()
    selected = {cid for answer in audit.answer_coverage
                if answer.status in {"answered", "partial"} and answer.answer
                for cid in answer.claim_ids}
    return tuple(item for item in supported if not has_questions or item.claim.kind == "fact"
                 or item.claim.id in projected - selected)


def audit_heading(audit, language):
    dimension = (
        {"feature": "功能", "pricing": "价格", "persona": "目标用户", "review": "用户反馈"}.get(
            audit.dimension, audit.dimension
        )
        if language.startswith("zh")
        else audit.dimension
    )
    return f"### {plain(audit.competitor)} — {plain(dimension)}"


def answer_decision_lines(
    answer, language, *, claims=(), answer_review_contract="subquestion-premises-v1", facts=(),
    decision_review=None,
):
    """Decision wording has one extension point for reviewed subquestion decisions."""
    zh = language.startswith("zh")
    if answer_review_contract == 'task-outcomes-v1':
        from packages.agents.writer.task_answer_outcomes import TaskOutcomeAuthority

        if (not isinstance(decision_review, TaskOutcomeAuthority)
                or not decision_review.matches(answer)):
            return []
        names = {'yes': '是', 'no': '否', 'depends': '需按条件判断', 'unknown': '尚不能确定'}
        lines = []
        if answer.conclusion in names:
            lines.append('  结论：' + names[answer.conclusion] if zh else
                         '  Conclusion: ' + answer.conclusion)
        if len(answer.subquestion_bindings) > 1:
            for b in answer.subquestion_bindings:
                if b.conclusion == 'not_applicable':
                    continue
                label = names.get(b.conclusion, b.conclusion) if zh else b.conclusion
                lines.append(f'  - {plain(b.question_quote)} — {label}')
        return lines
    if answer_review_contract in {'subquestion-premises-v5', 'subquestion-premises-v6'}:
        from packages.agents.writer.answer_coverage import coverage_resolution_reasons

        if coverage_resolution_reasons(answer, claims, facts=facts, require_subquestions=True,
                answer_review_contract=answer_review_contract, decision_review=decision_review):
            return []
    if answer.resolution == "clarification":
        return [
            "  需要先澄清问题中的条件。"
            if zh
            else "  Clarification is required before a definite conclusion."
        ]
    if answer.resolution == "insufficient":
        return []
    decisions = (
        {
            "yes": "结论：是",
            "no": "结论：否",
            "depends": "结论：需按条件判断",
            "unknown": "结论：尚不能确定",
            "not_applicable": "结论：不适用",
        }
        if zh
        else {
            "yes": "Conclusion: yes",
            "no": "Conclusion: no",
            "depends": "Conclusion: depends",
            "unknown": "Conclusion: unresolved",
            "not_applicable": "Conclusion: not applicable",
        }
    )
    branches = answer.subquestion_bindings
    from packages.agents.writer.complete_predicates import authority_question

    def decision_text(question, conclusion, ids):
        if (conclusion == 'yes' and authority_question(question) and decision_review is not None
                and decision_review.context.compact.get('delivery_policy')
                    == 'complete-predicates-v1'):
            selected = [plain(c['text']) for c in claims if c['id'] in ids]
            if selected:
                return ('结论：' if zh else 'Conclusion: ') + ' '.join(selected)
        return decisions[conclusion]

    lines = ['  ' + decision_text(answer.question, answer.conclusion, answer.claim_ids)]
    if (len(branches) > 1 or answer.status == "partial" and any(
            branch.conclusion == "unknown" for branch in branches)):
        from packages.agents.writer.answer_coverage import selection_binding_reasons
        from packages.agents.writer.subquestion_premises import subquestion_binding_reasons

        # Display existing decisions only after their exact selected text and
        # premise receipts still match. This check supplies no semantic verdict.
        if not selection_binding_reasons(answer, claims) and not subquestion_binding_reasons(
            answer, claims, answer_review_contract=answer_review_contract, facts=facts,
            decision_review=decision_review,
        ):
            by_id = {claim["id"]: claim for claim in claims}
            for branch in branches:
                sources = {sid for cid in branch.claim_ids
                           for sid in by_id[cid].get("source_ids", ())}
                citations = "".join(f"[source:{sid}]" for sid in sorted(sources))
                decision = decision_text(branch.question_quote, branch.conclusion, branch.claim_ids)
                lines.append((f"  - {plain(branch.question_quote)} — "
                              f"{decision} {citations}").rstrip())
    return lines


def question_coverage_lines(audit, language, *, detail=None, facts=None, decision_reviews=None):
    if not audit.answer_coverage:
        return []
    zh = language.startswith("zh")
    lines = ["#### 问题回答情况" if zh else "#### Question coverage", ""]
    names = {
        "answered": "已回答",
        "partial": "部分回答",
        "unanswered": "未回答",
        "unverified": "尚未核实",
    }
    supported = {item.claim.id: item.claim for item in audit.claims if item.status == "supported"}
    snapshot = next((item for item in getattr(detail, 'evidence_snapshots', ())
                     if item.id == detail.evidence_snapshot_id), None)
    if facts is None:
        facts = snapshot.facts if snapshot is not None else ()
    facts = tuple(fact for fact in facts
                  if fact.competitor == audit.competitor and fact.dimension == audit.dimension)
    from packages.agents.writer.task_answers import reviewed_task_answer_rows, task_answer_lines
    tasks = reviewed_task_answer_rows(detail, audit) if detail is not None else []
    if (audit.answer_review_contract in {'subquestion-premises-v6', 'task-outcomes-v1'}
            and decision_reviews is None):
        from packages.agents.writer.question_atomic_delivery import replay_decision_reviews

        try:
            decision_reviews = replay_decision_reviews(detail, audit) if detail is not None else {}
        except (ValueError, KeyError, TypeError, AttributeError, IndexError, RuntimeError):
            decision_reviews = {}
    for answer in audit.answer_coverage:
        decision_review = (decision_reviews or {}).get(answer.question_id)
        qualified = True
        if (audit.answer_review_contract == 'task-outcomes-v1'
                and answer.resolution not in {'clarification', 'insufficient'}):
            from packages.agents.writer.task_answer_outcomes import TaskOutcomeAuthority

            qualified = (isinstance(decision_review, TaskOutcomeAuthority)
                         and decision_review.matches(answer))
        if audit.answer_review_contract in {'subquestion-premises-v5', 'subquestion-premises-v6'}:
            from packages.agents.writer.answer_coverage import coverage_resolution_reasons
            from packages.agents.writer.complete_predicates import DELIVERY_POLICY
            from packages.agents.writer.price_answers import verified_missing_price_answer

            if (answer.resolution == 'insufficient'
                    and answer.reason.endswith(';delivery_policy=' + DELIVERY_POLICY)):
                qualified = verified_missing_price_answer(
                    detail, snapshot, answer, audit.competitor,
                    claims=tuple(supported.values()))
            else:
                qualified = not coverage_resolution_reasons(answer,
                    [claim.model_dump(mode='json') for claim in supported.values()], facts=facts,
                    require_subquestions=True, answer_review_contract=audit.answer_review_contract,
                    decision_review=decision_review)
        status = (names[answer.status] if zh else answer.status) if qualified else (
            names['unverified'] if zh else 'unverified')
        lines.append(f"- {plain(answer.question)} — {status}")
        if qualified and answer.answer and answer.status in {"answered", "partial"}:
            lines.extend(answer_decision_lines(answer, language,
                claims=[claim.model_dump(mode="json") for claim in supported.values()],
                answer_review_contract=audit.answer_review_contract or 'subquestion-premises-v1',
                facts=facts, decision_review=decision_review))
            sources = {
                sid
                for claim_id in answer.claim_ids
                if claim_id in supported
                for sid in supported[claim_id].source_ids
            }
            citations = "".join(f"[source:{sid}]" for sid in sorted(sources))
            lines.append(f"  {plain(answer.answer)} {citations}".rstrip())
        else:
            lines.append(
                "  本次已审核证据尚未完整覆盖此问题。"
                if zh
                else "  The reviewed evidence does not yet fully answer this question."
            )
        lines.extend(task_answer_lines([t for t in tasks if t['question_id'] == answer.question_id], language))
    return [*lines, ""]


def question_coverage_matches(report, audit, language, *, audits=(), detail=None,
                              decision_reviews=None):
    """Check the complete status/decision/answer block in its own audit section."""
    expected = question_coverage_lines(audit, language, detail=detail,
                                       decision_reviews=decision_reviews)
    if not expected:
        return True
    lines = report.splitlines()
    headings = [index for index, line in enumerate(lines) if line == audit_heading(audit, language)]
    if len(headings) != 1:
        return False
    start = headings[0] + 1
    end = next(
        (
            index
            for index in range(start, len(lines))
            if lines[index].startswith(("# ", "## ", "### "))
        ),
        len(lines),
    )
    blocks = [index for index in range(start, end) if lines[index] == expected[0]]
    if len(blocks) != 1:
        return False
    # A duplicate intact block elsewhere cannot excuse a changed local block.
    exact = "\n".join(expected).rstrip("\n")
    expected_count = (
        sum(question_coverage_lines(other, language, detail=detail,
                decision_reviews=decision_reviews if other == audit else None) == expected
            for other in audits) or 1
    )
    return (
        report.count(exact) == expected_count
        and lines[blocks[0] : blocks[0] + len(expected)] == expected
    )
