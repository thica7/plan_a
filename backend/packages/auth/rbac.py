from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EnterpriseRole = Literal["owner", "admin", "analyst", "reviewer", "viewer"]
PolicyEffect = Literal["allow", "deny"]
AuthPolicyEngine = Literal["internal", "opa", "cerbos"]
PolicyDecisionEngine = Literal["internal-opa-compatible", "opa", "cerbos"]

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
    policy_engine: AuthPolicyEngine = "internal"
    policy_url: str | None = None
    policy_timeout_seconds: float = 1.0


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
    engine: PolicyDecisionEngine = "internal-opa-compatible"
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
    if user.workspace_id is not None and user.workspace_id != workspace_id:
        return _decision(
            allowed=False,
            engine=_decision_engine_for(user.policy_engine),
            subject_id=user.user_id,
            role=user.role,
            scoped_workspace_id=user.workspace_id,
            workspace_id=workspace_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            required_role=required_role,
            matched_rules=[
                PolicyRuleMatch(
                    rule_id="deny_cross_workspace_scope",
                    effect="deny",
                    message="User workspace scope does not match requested workspace.",
                )
            ],
            reason="Cross-workspace access is denied.",
        )

    if user.policy_engine in {"opa", "cerbos"}:
        return _evaluate_external_policy(
            user,
            workspace_id,
            action,
            target_type=target_type,
            target_id=target_id,
            required_role=required_role,
        )

    if not can_perform(user.role, action):
        return _decision(
            allowed=False,
            engine="internal-opa-compatible",
            subject_id=user.user_id,
            role=user.role,
            scoped_workspace_id=user.workspace_id,
            workspace_id=workspace_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            required_role=required_role,
            matched_rules=[
                PolicyRuleMatch(
                    rule_id="deny_role_below_minimum",
                    effect="deny",
                    message=f"Action requires role {required_role} or higher.",
                )
            ],
            reason=f"Role {user.role} is below required role {required_role}.",
        )

    return _decision(
        allowed=True,
        engine="internal-opa-compatible",
        subject_id=user.user_id,
        role=user.role,
        scoped_workspace_id=user.workspace_id,
        workspace_id=workspace_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        required_role=required_role,
        matched_rules=[
            PolicyRuleMatch(
                rule_id="allow_workspace_role_minimum",
                effect="allow",
                message="Workspace scope and minimum role checks passed.",
            )
        ],
        reason="Allowed by workspace RBAC policy.",
    )


def can_access_workspace(
    user: EnterpriseUserContext,
    workspace_id: str,
    action: str,
) -> bool:
    return evaluate_access_policy(user, workspace_id, action).allowed


def _evaluate_external_policy(
    user: EnterpriseUserContext,
    workspace_id: str,
    action: str,
    *,
    target_type: str,
    target_id: str | None,
    required_role: EnterpriseRole,
) -> PolicyDecision:
    if not user.policy_url:
        return _external_deny(
            user,
            workspace_id,
            action,
            target_type=target_type,
            target_id=target_id,
            required_role=required_role,
            rule_id="deny_external_policy_unconfigured",
            reason=f"{user.policy_engine.upper()} policy engine is enabled without a policy URL.",
        )

    payload = (
        _opa_payload(user, workspace_id, action, target_type=target_type, target_id=target_id)
        if user.policy_engine == "opa"
        else _cerbos_payload(
            user,
            workspace_id,
            action,
            target_type=target_type,
            target_id=target_id,
        )
    )
    try:
        raw = _post_policy_json(
            user.policy_url,
            payload,
            timeout_seconds=max(0.1, min(user.policy_timeout_seconds, 10.0)),
        )
        allowed, reason = _parse_external_decision(raw, action, engine=user.policy_engine)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return _external_deny(
            user,
            workspace_id,
            action,
            target_type=target_type,
            target_id=target_id,
            required_role=required_role,
            rule_id="deny_external_policy_unavailable",
            reason=f"{user.policy_engine.upper()} policy engine unavailable: {type(exc).__name__}.",
        )

    return _decision(
        allowed=allowed,
        engine=_decision_engine_for(user.policy_engine),
        subject_id=user.user_id,
        role=user.role,
        scoped_workspace_id=user.workspace_id,
        workspace_id=workspace_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        required_role=required_role,
        matched_rules=[
            PolicyRuleMatch(
                rule_id="external_policy_allow" if allowed else "external_policy_deny",
                effect="allow" if allowed else "deny",
                message=reason,
            )
        ],
        reason=reason,
    )


def _external_deny(
    user: EnterpriseUserContext,
    workspace_id: str,
    action: str,
    *,
    target_type: str,
    target_id: str | None,
    required_role: EnterpriseRole,
    rule_id: str,
    reason: str,
) -> PolicyDecision:
    return _decision(
        allowed=False,
        engine=_decision_engine_for(user.policy_engine),
        subject_id=user.user_id,
        role=user.role,
        scoped_workspace_id=user.workspace_id,
        workspace_id=workspace_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        required_role=required_role,
        matched_rules=[PolicyRuleMatch(rule_id=rule_id, effect="deny", message=reason)],
        reason=reason,
    )


def _decision(
    *,
    allowed: bool,
    engine: PolicyDecisionEngine,
    subject_id: str,
    role: EnterpriseRole,
    scoped_workspace_id: str | None,
    workspace_id: str,
    action: str,
    target_type: str,
    target_id: str | None,
    required_role: EnterpriseRole,
    matched_rules: list[PolicyRuleMatch],
    reason: str,
) -> PolicyDecision:
    return PolicyDecision(
        allowed=allowed,
        effect="allow" if allowed else "deny",
        engine=engine,
        subject_id=subject_id,
        role=role,
        scoped_workspace_id=scoped_workspace_id,
        workspace_id=workspace_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        required_role=required_role,
        matched_rules=matched_rules,
        reason=reason,
    )


def _decision_engine_for(engine: AuthPolicyEngine) -> PolicyDecisionEngine:
    if engine == "opa":
        return "opa"
    if engine == "cerbos":
        return "cerbos"
    return "internal-opa-compatible"


def _opa_payload(
    user: EnterpriseUserContext,
    workspace_id: str,
    action: str,
    *,
    target_type: str,
    target_id: str | None,
) -> dict[str, object]:
    return {
        "input": {
            "subject": {
                "id": user.user_id,
                "role": user.role,
                "workspace_id": user.workspace_id,
            },
            "resource": {
                "workspace_id": workspace_id,
                "type": target_type,
                "id": target_id or workspace_id,
            },
            "action": action,
        }
    }


def _cerbos_payload(
    user: EnterpriseUserContext,
    workspace_id: str,
    action: str,
    *,
    target_type: str,
    target_id: str | None,
) -> dict[str, object]:
    return {
        "principal": {
            "id": user.user_id,
            "roles": [user.role],
            "attr": {"workspace_id": user.workspace_id},
        },
        "resources": [
            {
                "resource": {
                    "kind": target_type,
                    "id": target_id or workspace_id,
                    "attr": {"workspace_id": workspace_id},
                },
                "actions": [action],
            }
        ],
    }


def _post_policy_json(
    url: str,
    payload: dict[str, object],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        raw = response.read().decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Policy engine response must be a JSON object.")
    return parsed


def _parse_external_decision(
    response: dict[str, Any],
    action: str,
    *,
    engine: AuthPolicyEngine,
) -> tuple[bool, str]:
    if engine == "opa":
        return _parse_opa_decision(response)
    return _parse_cerbos_decision(response, action)


def _parse_opa_decision(response: dict[str, Any]) -> tuple[bool, str]:
    result = response.get("result")
    if isinstance(result, bool):
        return result, "Allowed by OPA policy." if result else "Denied by OPA policy."
    if isinstance(result, dict):
        allowed = bool(result.get("allow", result.get("allowed", False)))
        reason = str(
            result.get("reason")
            or result.get("message")
            or ("Allowed by OPA policy." if allowed else "Denied by OPA policy.")
        )
        return allowed, reason
    raise ValueError("OPA response must contain result boolean or object.")


def _parse_cerbos_decision(response: dict[str, Any], action: str) -> tuple[bool, str]:
    if isinstance(response.get("allowed"), bool):
        allowed = bool(response["allowed"])
        return allowed, "Allowed by Cerbos policy." if allowed else "Denied by Cerbos policy."
    results = response.get("results") or response.get("resourceInstances")
    if not isinstance(results, list) or not results:
        raise ValueError("Cerbos response must contain results.")
    actions = results[0].get("actions") if isinstance(results[0], dict) else None
    if not isinstance(actions, dict):
        raise ValueError("Cerbos result must contain actions.")
    value = actions.get(action)
    allowed = value is True or str(value).upper() in {"EFFECT_ALLOW", "ALLOW", "ALLOWED"}
    return allowed, "Allowed by Cerbos policy." if allowed else "Denied by Cerbos policy."
