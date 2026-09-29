from __future__ import annotations

import html
import json
import re

from packages.schema.models import DecisionBrief


def decision_brief_fields(brief: DecisionBrief | None) -> dict[str, str]:
    if brief is None:
        return {}
    return {
        key: value.strip()
        for key, value in brief.model_dump().items()
        if value.strip()
    }


def decision_brief_prompt_context(brief: DecisionBrief | None) -> str:
    fields = decision_brief_fields(brief)
    if not fields:
        return ""
    return (
        "User-provided decision brief (context, not evidence or a source; "
        "do not cite it as a competitor fact): "
        f"{json.dumps(fields, ensure_ascii=False)}\n"
    )


def safe_decision_brief_text(value: str) -> str:
    return html.escape(re.sub(r"\s+", " ", value)).replace("[", "［").replace("]", "］")
