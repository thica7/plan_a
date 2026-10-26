"""Decode final-QA request fixtures without changing legacy production parsing."""

import json


def review_payload(raw):
    value = json.loads(raw)
    if isinstance(value, dict) and "c" in value:
        from packages.agents.qa.question_review_encoding import loads

        return loads(raw)
    if isinstance(value, dict) and "question_contexts" in value:
        # Offline doubles consume flat rows. The actual model receives the
        # complete directly readable named context unchanged in its JSON wire.
        value["findings"] = [
            {
                **value["question_contexts"][row["context_id"]],
                **{key: item for key, item in row.items() if key != "context_id"},
            }
            for row in value["findings"]
        ]
    return value
