from __future__ import annotations

import json
from typing import Any

from packages.agents import SubagentContext


def inspect_sources(
    service,
    record,
    *,
    dimension: str,
    context: SubagentContext,
    dimension_sources: list[dict[str, Any]],
) -> dict[str, object]:
    detail = record.detail
    by_competitor = {
        competitor: sum(
            1
            for source in dimension_sources
            if service._source_dict_matches_competitor(source, competitor)
        )
        for competitor in detail.plan.competitors
    }
    cards = [
        {
            "id": str(source.get("id") or ""),
            "competitor": str(source.get("competitor") or ""),
            "title": str(source.get("title") or ""),
            "url": str(source.get("url") or ""),
            "snippet": service._preview(str(source.get("snippet") or ""), 180),
            "confidence": source.get("confidence"),
        }
        for source in dimension_sources[:12]
    ]
    output: dict[str, object] = {
        "dimension": dimension,
        "source_count": len(dimension_sources),
        "by_competitor": by_competitor,
        "missing_competitors": [
            competitor for competitor, count in by_competitor.items() if count == 0
        ],
        "source_cards": cards,
    }
    service._trace_local_tool(
        record,
        agent="analyst",
        subagent=context.subagent,
        name="inspect_sources",
        input_text=json.dumps({"dimension": dimension}, ensure_ascii=False),
        output_text=json.dumps(output, ensure_ascii=False),
        context=context,
        metadata={
            "source_count": len(dimension_sources),
            "missing_competitor_count": sum(1 for count in by_competitor.values() if count == 0),
        },
    )
    return output


def validate_source_ids(
    service,
    record,
    *,
    dimension: str,
    context: SubagentContext,
    dimension_sources: list[dict[str, Any]],
    requested_source_ids: list[str],
) -> dict[str, object]:
    known_source_ids = {
        str(source.get("id") or "")
        for source in dimension_sources
        if str(source.get("id") or "").strip()
    }
    valid_source_ids = [source_id for source_id in requested_source_ids if source_id in known_source_ids]
    unknown_source_ids = [source_id for source_id in requested_source_ids if source_id not in known_source_ids]
    output: dict[str, object] = {
        "dimension": dimension,
        "requested_source_ids": requested_source_ids,
        "valid_source_ids": valid_source_ids,
        "unknown_source_ids": unknown_source_ids,
        "known_source_count": len(known_source_ids),
    }
    service._trace_local_tool(
        record,
        agent="analyst",
        subagent=context.subagent,
        name="validate_citations",
        input_text=json.dumps({"source_ids": requested_source_ids}, ensure_ascii=False),
        output_text=json.dumps(output, ensure_ascii=False),
        context=context,
        metadata={
            "requested_count": len(requested_source_ids),
            "valid_count": len(valid_source_ids),
            "unknown_count": len(unknown_source_ids),
        },
    )
    return output
