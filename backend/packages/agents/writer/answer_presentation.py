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
    answer, language, *, claims=(), answer_review_contract="subquestion-premises-v1", facts=()
):
    """Decision wording has one extension point for reviewed subquestion decisions."""
    zh = language.startswith("zh")
    if answer_review_contract == 'subquestion-premises-v5':
        from packages.agents.writer.answer_coverage import coverage_resolution_reasons

        if coverage_resolution_reasons(answer, claims, facts=facts, require_subquestions=True,
                answer_review_contract=answer_review_contract):
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
    lines = ["  " + decisions[answer.conclusion]]
    branches = answer.subquestion_bindings
    if (len(branches) > 1 or answer.status == "partial" and any(
            branch.conclusion == "unknown" for branch in branches)):
        from packages.agents.writer.answer_coverage import selection_binding_reasons
        from packages.agents.writer.subquestion_premises import subquestion_binding_reasons

        # Display existing decisions only after their exact selected text and
        # premise receipts still match. This check supplies no semantic verdict.
        if not selection_binding_reasons(answer, claims) and not subquestion_binding_reasons(
            answer, claims, answer_review_contract=answer_review_contract, facts=facts
        ):
            by_id = {claim["id"]: claim for claim in claims}
            for branch in branches:
                sources = {sid for cid in branch.claim_ids
                           for sid in by_id[cid].get("source_ids", ())}
                citations = "".join(f"[source:{sid}]" for sid in sorted(sources))
                lines.append((f"  - {plain(branch.question_quote)} — "
                              f"{decisions[branch.conclusion]} {citations}").rstrip())
    return lines


def question_coverage_lines(audit, language, *, detail=None, facts=None):
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
    if facts is None:
        snapshot = next((item for item in getattr(detail, 'evidence_snapshots', ())
                         if item.id == detail.evidence_snapshot_id), None)
        facts = snapshot.facts if snapshot is not None else ()
    facts = tuple(fact for fact in facts
                  if fact.competitor == audit.competitor and fact.dimension == audit.dimension)
    from packages.agents.writer.task_answers import reviewed_task_answer_rows, task_answer_lines
    tasks = reviewed_task_answer_rows(detail, audit) if detail is not None else []
    for answer in audit.answer_coverage:
        qualified = True
        if audit.answer_review_contract == 'subquestion-premises-v5':
            from packages.agents.writer.answer_coverage import coverage_resolution_reasons

            qualified = not coverage_resolution_reasons(answer,
                [claim.model_dump(mode='json') for claim in supported.values()], facts=facts,
                require_subquestions=True, answer_review_contract=audit.answer_review_contract)
        status = (names[answer.status] if zh else answer.status) if qualified else (
            names['unverified'] if zh else 'unverified')
        lines.append(f"- {plain(answer.question)} — {status}")
        if qualified and answer.answer and answer.status in {"answered", "partial"}:
            lines.extend(answer_decision_lines(answer, language,
                claims=[claim.model_dump(mode="json") for claim in supported.values()],
                answer_review_contract=audit.answer_review_contract or 'subquestion-premises-v1',
                facts=facts))
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


def question_coverage_matches(report, audit, language, *, audits=(), detail=None):
    """Check the complete status/decision/answer block in its own audit section."""
    expected = question_coverage_lines(audit, language, detail=detail)
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
        sum(question_coverage_lines(other, language, detail=detail) == expected for other in audits) or 1
    )
    return (
        report.count(exact) == expected_count
        and lines[blocks[0] : blocks[0] + len(expected)] == expected
    )
