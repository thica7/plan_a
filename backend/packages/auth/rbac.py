from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EnterpriseRole = Literal["owner", "admin", "analyst", "reviewer", "viewer"]

_ROLE_RANK: dict[EnterpriseRole, int] = {
    "viewer": 0,
    "reviewer": 1,
    "analyst": 2,
    "admin": 3,
    "owner": 4,
}

_ACTION_MIN_ROLE: dict[str, EnterpriseRole] = {
    "workspace:read": "viewer",
    "workspace:write": "admin",
    "project:read": "viewer",
    "project:write": "analyst",
    "competitor:read": "viewer",
    "evidence:read": "viewer",
    "evidence:write": "analyst",
    "evidence:review": "reviewer",
    "source:read": "viewer",
    "source:write": "analyst",
    "report:read": "viewer",
    "report:write": "analyst",
    "report:review": "reviewer",
    "audit:read": "admin",
}


@dataclass(frozen=True)
class EnterpriseUserContext:
    user_id: str
    role: EnterpriseRole
    workspace_id: str | None = None


def normalize_role(value: str | None) -> EnterpriseRole:
    role = (value or "owner").strip().lower()
    if role in _ROLE_RANK:
        return role  # type: ignore[return-value]
    return "viewer"


def can_perform(role: EnterpriseRole, action: str) -> bool:
    required = _ACTION_MIN_ROLE.get(action, "owner")
    return _ROLE_RANK[role] >= _ROLE_RANK[required]


def can_access_workspace(
    user: EnterpriseUserContext,
    workspace_id: str,
    action: str,
) -> bool:
    if user.workspace_id is not None and user.workspace_id != workspace_id:
        return False
    return can_perform(user.role, action)
