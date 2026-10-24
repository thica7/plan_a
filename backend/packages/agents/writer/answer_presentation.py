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


def answer_decision_lines(answer, language):
    """Decision wording has one extension point for reviewed subquestion decisions."""
    zh = language.startswith("zh")
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
    return ["  " + decisions[answer.conclusion]]


def question_coverage_lines(audit, language, *, detail=None):
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
    from packages.agents.writer.task_answers import reviewed_task_answer_rows, task_answer_lines
    tasks = reviewed_task_answer_rows(detail, audit) if detail is not None else []
    for answer in audit.answer_coverage:
        status = names[answer.status] if zh else answer.status
        lines.append(f"- {plain(answer.question)} — {status}")
        if answer.answer and answer.status in {"answered", "partial"}:
            lines.extend(answer_decision_lines(answer, language))
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
