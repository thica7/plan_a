from __future__ import annotations

import json

from packages.agents import SubagentContext
from packages.identity import compute_raw_source_id
from packages.research.discovery import homepage_candidates, trusted_registry_candidates
from packages.research.models import ResearchBrief
from packages.schema.api_dto import RunDetail
from packages.schema.models import RawSource
from packages.search import SearchResult
from packages.tools import search_review_site_queries, survey_simulator


async def collect_competitor_with_skill_tools(
    service,
    record,
    *,
    dimension: str,
    competitor: str,
    context: SubagentContext,
    qa_feedback: list[dict[str, object]],
) -> list[RawSource]:
    detail: RunDetail = record.detail
    skill = service._skill_registry.get(dimension)
    allowlist = set(skill.tools_allowlist if skill is not None else [])
    sources: list[RawSource] = []

    if "find_official_docs" in allowlist:
        brief = ResearchBrief(
            run_id=detail.id,
            topic=detail.topic,
            competitor=competitor,
            dimension=dimension,
            homepage_hint=detail.plan.homepage_hints.get(competitor),
            execution_mode=detail.execution_mode,
        )
        candidates = [*trusted_registry_candidates(brief), *homepage_candidates(brief)]
        service._trace_local_tool(
            record,
            agent="collector",
            subagent=context.subagent,
            name="find_official_docs",
            input_text=json.dumps(
                {
                    "competitor": competitor,
                    "dimension": dimension,
                    "homepage_hint": detail.plan.homepage_hints.get(competitor),
                },
                ensure_ascii=False,
            ),
            output_text=json.dumps(
                [candidate.model_dump(mode="json") for candidate in candidates],
                ensure_ascii=False,
            ),
            context=context,
            metadata={"candidate_count": len(candidates)},
        )
        for candidate in candidates[:2]:
            source = await service._source_from_search_result(
                detail,
                competitor,
                dimension,
                SearchResult(title=candidate.title, url=candidate.url, snippet=candidate.snippet),
                record,
                context,
                candidate=candidate,
            )
            if source is not None:
                sources.append(source)
                break

    if not sources and "search_review_site" in allowlist and service._search.is_enabled:
        plan = search_review_site_queries(competitor=competitor, topic=detail.topic)
        service._trace_local_tool(
            record,
            agent="collector",
            subagent=context.subagent,
            name="search_review_site",
            input_text=json.dumps(
                {"competitor": competitor, "topic": detail.topic}, ensure_ascii=False
            ),
            output_text=json.dumps(plan.__dict__, ensure_ascii=False),
            context=context,
            metadata={"query_count": len(plan.queries)},
        )
        for query in plan.queries[:2]:
            results = await service._trace_search(
                record,
                agent="collector",
                subagent=context.subagent,
                query=query,
                max_results=3,
                context=context,
            )
            for result in results:
                source = await service._source_from_search_result(
                    detail,
                    competitor,
                    dimension,
                    result,
                    record,
                    context,
                )
                if source is not None:
                    sources.append(source)
                    return sources

    if not sources and "survey_simulator" in allowlist:
        records = survey_simulator(
            topic=detail.topic,
            competitor=competitor,
            dimension=dimension,
            qa_feedback=qa_feedback,
        )
        service._trace_local_tool(
            record,
            agent="collector",
            subagent=context.subagent,
            name="survey_simulator",
            input_text=json.dumps(
                {"topic": detail.topic, "competitor": competitor, "dimension": dimension},
                ensure_ascii=False,
            ),
            output_text=json.dumps([item.__dict__ for item in records], ensure_ascii=False),
            context=context,
            metadata={"record_count": len(records), "source_type": "interview_record"},
        )
        for item in records[:1]:
            title = f"{item.respondent} interview note"
            source = RawSource(
                id=compute_raw_source_id(
                    source_type="interview_record",
                    competitor=competitor,
                    dimension=dimension,
                    content_hash=item.content_hash,
                    title=title,
                    snippet=item.summary,
                    run_id=detail.id,
                    source_role="skill-tool-survey",
                ),
                competitor=competitor,
                dimension=dimension,
                source_type="interview_record",
                title=title,
                snippet=item.summary,
                content_hash=item.content_hash,
                confidence=0.56,
            )
            if service._source_is_usable(source):
                sources.append(source)
    return sources
