from __future__ import annotations

import json
import re
from typing import Any


class JsonExtractionError(ValueError):
    pass


def strict_json_object(content: str) -> dict[str, Any]:
    """New explicit protocols accept exactly one object, with unique members."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise JsonExtractionError("Duplicate JSON member")
            result[key] = value
        return result

    result = json.loads(content, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise JsonExtractionError("JSON root must be an object")
    return result


def extract_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return loads_first_json_object(stripped)

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced:
        return loads_first_json_object(fenced.group(1))

    first = stripped.find("{")
    if first >= 0:
        return loads_first_json_object(stripped[first:])

    raise JsonExtractionError("LLM response did not contain a JSON object.")


def loads_first_json_object(content: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    parsed, _ = decoder.raw_decode(content.strip())
    if not isinstance(parsed, dict):
        raise JsonExtractionError("LLM response JSON root was not an object.")
    return parsed
