from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EnterpriseRole = Literal["owner", "admin", "analyst", "reviewer", "viewer"]
PolicyEffect = Literal["allow", "deny"]

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
    "artifact:read": "viewer",
    "artifact:write": "analyst",
    "report:read": "viewer",
    "report:write": "analyst",
    "report:review": "reviewer",
    "notification:read": "viewer",
    "notification:write": "analyst",
    "audit:read": "admin",
}


@dataclass(frozen=True)
class EnterpriseUserContext:
    user_id: str
    role: EnterpriseRole
    workspace_id: str | None = None


class PolicyEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=120)
    action: str = Field(min_length=1, max_length=120)
    target_type: str = Field(default="workspace", min_length=1, max_length=120)
    target_id: str | None = Field(default=None, min_length=1, max_length=200)


class PolicyRuleMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    effect: PolicyEffect
    message: str


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    effect: PolicyEffect
    engine: Literal["internal-opa-compatible"] = "internal-opa-compatible"
    policy_version: str = "2026-05-phase5-rbac"
    subject_id: str
    role: EnterpriseRole
    scoped_workspace_id: str | None = None
    workspace_id: str
    action: str
    target_type: str = "workspace"
    target_id: str | None = None
    required_role: EnterpriseRole
    matched_rules: list[PolicyRuleMatch] = Field(default_factory=list)
    reason: str


def normalize_role(value: str | None) -> EnterpriseRole:
    role = (value or "owner").strip().lower()
    if role in _ROLE_RANK:
        return role  # type: ignore[return-value]
    return "viewer"


def can_perform(role: EnterpriseRole, action: str) -> bool:
    required = _ACTION_MIN_ROLE.get(action, "owner")
    return _ROLE_RANK[role] >= _ROLE_RANK[required]


def required_role_for_action(action: str) -> EnterpriseRole:
    return _ACTION_MIN_ROLE.get(action, "owner")


def list_policy_actions() -> dict[str, EnterpriseRole]:
    return dict(sorted(_ACTION_MIN_ROLE.items()))


def evaluate_access_policy(
    user: EnterpriseUserContext,
    workspace_id: str,
    action: str,
    *,
    target_type: str = "workspace",
    target_id: str | None = None,
) -> PolicyDecision:
    required_role = required_role_for_action(action)
    matched_rules: list[PolicyRuleMatch] = []
    if user.workspace_id is not None and user.workspace_id != workspace_id:
        matched_rules.append(
            PolicyRuleMatch(
                rule_id="deny_cross_workspace_scope",
                effect="deny",
                message="User workspace scope does not match requested workspace.",
            )
        )
        return PolicyDecision(
            allowed=False,
            effect="deny",
            subject_id=user.user_id,
            role=user.role,
            scoped_workspace_id=user.workspace_id,
            workspace_id=workspace_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            required_role=required_role,
            matched_rules=matched_rules,
            reason="Cross-workspace access is denied.",
        )

    if not can_perform(user.role, action):
        matched_rules.append(
            PolicyRuleMatch(
                rule_id="deny_role_below_minimum",
                effect="deny",
                message=f"Action requires role {required_role} or higher.",
            )
        )
        return PolicyDecision(
            allowed=False,
            effect="deny",
            subject_id=user.user_id,
            role=user.role,
            scoped_workspace_id=user.workspace_id,
            workspace_id=workspace_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            required_role=required_role,
            matched_rules=matched_rules,
            reason=f"Role {user.role} is below required role {required_role}.",
        )

    matched_rules.append(
        PolicyRuleMatch(
            rule_id="allow_workspace_role_minimum",
            effect="allow",
            message="Workspace scope and minimum role checks passed.",
        )
    )
    return PolicyDecision(
        allowed=True,
        effect="allow",
        subject_id=user.user_id,
        role=user.role,
        scoped_workspace_id=user.workspace_id,
        workspace_id=workspace_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        required_role=required_role,
        matched_rules=matched_rules,
        reason="Allowed by workspace RBAC policy.",
    )


def can_access_workspace(
    user: EnterpriseUserContext,
    workspace_id: str,
    action: str,
) -> bool:
    return evaluate_access_policy(user, workspace_id, action).allowed
