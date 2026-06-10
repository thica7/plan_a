from __future__ import annotations

from collections.abc import Iterable, Sequence

from packages.schema.models import QCIssue, RawSource
from packages.schema.rag import GapRetrievalContext, RetrievalRecord

USER_RESEARCH_SOURCE_TYPES = {
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_note",
    "manual",
}


def build_run_grounding_prompt(
    *,
    sources: Iterable[RawSource],
    qa_findings: Iterable[QCIssue] = (),
    max_sources: int = 12,
    max_gap_findings: int = 6,
    kb_context: str | None = None,
) -> str:
    source_lines = _source_lines(sources, max_sources=max_sources)
    gap_lines = _gap_lines(qa_findings, max_gap_findings=max_gap_findings)
    lines = [
        "Grounded evidence contract:",
        "- Cite factual claims only with the allowed source tokens listed below.",
        "- Do not invent source IDs; use [source:ID] or [source:ID#chunk:n] only.",
        "- Treat low-confidence, search-only, and user-research sources as tentative.",
        "- If no listed source supports a claim, name the evidence gap instead.",
        "",
        "Allowed source tokens:",
    ]
    lines.extend(source_lines or ["- none"])
    if gap_lines:
        lines.extend(["", "Open evidence-gap retrieval targets:", *gap_lines])
    prompt = "\n".join(lines)
    if kb_context is not None:
        prompt += f"\n\n## KB Evidence Context\n{kb_context}"
    return prompt


def build_retrieval_grounding_prompt(
    contexts: Sequence[GapRetrievalContext],
    *,
    max_records: int = 8,
) -> str:
    lines = [
        "RAG retrieval context:",
        "- Use these retrieval records only as grounding context for the matching gap.",
        "- Preserve chunk-level citations when a chunk is the direct support.",
    ]
    records: list[RetrievalRecord] = []
    for context in contexts:
        if context.query:
            lines.append(f"- gap={context.gap_id}; query={context.query}")
        records.extend(context.records)
    formatted = format_retrieval_records_for_prompt(records, max_records=max_records)
    if formatted:
        lines.extend(["", formatted])
    return "\n".join(lines)


def format_retrieval_records_for_prompt(
    records: Sequence[RetrievalRecord],
    *,
    max_records: int = 8,
    max_snippet_chars: int = 420,
) -> str:
    lines: list[str] = []
    for record in list(records)[:max_records]:
        token = f"[source:{record.evidence_id}#chunk:{record.chunk_index}]"
        snippet = _trim(record.snippet, max_snippet_chars)
        lines.append(
            f"{token} {record.title} ({record.source_type}, dimension={record.dimension}, "
            f"hybrid={record.score}, bm25={record.bm25_score}, vector={record.vector_score}, "
            f"rerank={record.rerank_score}): {snippet}"
        )
    return "\n".join(lines)


def _source_lines(sources: Iterable[RawSource], *, max_sources: int) -> list[str]:
    sorted_sources = sorted(
        sources,
        key=lambda source: (
            _source_priority(source),
            -source.confidence,
            source.competitor.casefold(),
            source.dimension.casefold(),
            source.id,
        ),
    )
    lines: list[str] = []
    for source in sorted_sources[:max_sources]:
        flags = _source_flags(source)
        title = _trim(source.title, 120)
        snippet = _trim(source.snippet, 220)
        url = str(source.url) if source.url else ""
        line = (
            f"- [source:{source.id}] competitor={source.competitor}; "
            f"dimension={source.dimension}; type={source.source_type}; "
            f"confidence={source.confidence:.2f}; title={title}"
        )
        if flags:
            line = f"{line}; flags={','.join(flags)}"
        if url:
            line = f"{line}; url={url}"
        if snippet:
            line = f"{line}; snippet={snippet}"
        lines.append(line)
    return lines


def _gap_lines(
    qa_findings: Iterable[QCIssue],
    *,
    max_gap_findings: int,
) -> list[str]:
    lines: list[str] = []
    for issue in qa_findings:
        if len(lines) >= max_gap_findings:
            break
        if issue.target_agent != "collector" or issue.severity not in {"warn", "blocker"}:
            continue
        scope = issue.redo_scope
        competitor = scope.target_competitor or issue.target_competitor or "all competitors"
        dimension = scope.target_subagent or issue.target_subagent or issue.field_path
        query = " ".join(f"{competitor} {dimension} {issue.problem}".split())[:220]
        lines.append(
            f"- gap={issue.id}; severity={issue.severity}; competitor={competitor}; "
            f"dimension={dimension}; suggested_query={query}"
        )
    return lines


def _source_priority(source: RawSource) -> int:
    source_type = source.source_type.casefold()
    if source_type in {"webpage_verified", "official_docs", "official_webpage"}:
        return 0
    if source_type in {"fetched_webpage", "source_snapshot", "artifact"}:
        return 1
    if source_type in USER_RESEARCH_SOURCE_TYPES:
        return 2
    if source_type in {"web_search_result", "llm_public_knowledge"}:
        return 4
    return 3


def _source_flags(source: RawSource) -> list[str]:
    flags: list[str] = []
    source_type = source.source_type.casefold()
    if source.confidence < 0.75:
        flags.append("low_confidence")
    if source_type in {"web_search_result", "llm_public_knowledge"}:
        flags.append("lead_not_proof")
    if source_type in USER_RESEARCH_SOURCE_TYPES:
        flags.append("directional_user_research")
    return flags


def _trim(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."
