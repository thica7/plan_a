"""Deterministic business request identity, including all model defaults."""

import hashlib
import json

from packages.schema.api_dto import RunCreateRequest


def canonical_request(request: RunCreateRequest) -> tuple[dict, str]:
    payload = request.model_dump(mode="json")
    payload.pop("idempotency_key", None)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return payload, hashlib.sha256(encoded.encode("utf-8")).hexdigest()
