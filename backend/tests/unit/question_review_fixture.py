"""Decode final-QA request fixtures without changing legacy production parsing."""

import json


def review_payload(raw):
    value = json.loads(raw)
    if isinstance(value, dict) and "c" in value:
        from packages.agents.qa.question_review_encoding import loads

        return loads(raw)
    return value
