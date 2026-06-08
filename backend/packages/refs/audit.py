from __future__ import annotations

from packages.identity import stable_prefixed_id


def audit_relationship_resource_id(resource_type: str, *parts: object) -> str:
    return stable_prefixed_id(resource_type, *parts, length=20)
