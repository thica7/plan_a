# Checkpoint 3 Product-Flow Verification

Date: 2026-06-07

## Verdict

Checkpoint 3 enterprise product hardening core is accepted.

This verification covers the product flow required by
`docs/enterprise_execution_master_plan.md`:

- Approval-gated report publishing.
- Rejection -> manual correction -> new draft revision.
- Artifact/source snapshot/report export governance.
- Workspace/RBAC isolation.
- Decision replay for audit-grade product review.

## Validation Command

```powershell
conda run -n bd-competiscope-v2 python -m pytest backend/tests/unit/test_enterprise_store.py::test_enterprise_router_blocks_direct_publish_status_without_approval backend/tests/unit/test_enterprise_store.py::test_manual_report_revision_after_rejection_creates_audited_draft backend/tests/unit/test_enterprise_store.py::test_enterprise_router_enforces_rbac_workspace_scope backend/tests/unit/test_h10_governance.py::test_h10_enterprise_routes_are_callable backend/tests/unit/test_observability.py::test_decision_replay_includes_enterprise_audit_governance_events -q
```

Result:

```text
5 passed in 1.65s
```

## What This Proves

- Reports cannot be directly moved to review, approval, rejection, or publish
  states through plain upsert.
- Approval activity moves reports through `in_review` and `approved`, and
  publish requires both approval and ReleaseGate success.
- Rejected reports can be manually revised into a new draft without overwriting
  the rejected version.
- Manual corrections emit report-version audit events and MemoryAgent feedback.
- Artifacts carry report_version_id, retention_policy, and compliance_metadata.
- Web snapshots, report exports, imported survey/interview materials, and
  source registry records share the enterprise artifact/source governance path.
- Workspace-scoped users cannot read or mutate resources from another workspace
  across project, report, evidence, artifact, source registry, memory, and audit
  routes.
- Decision replay surfaces source review, report lifecycle, manual revision,
  artifact export, memory feedback, and ReleaseGate/gap-fill review events.

## Remaining Production Hardening

These are intentionally not claimed as complete:

- Live Postgres RLS integration verification against a real Postgres instance.
- Full SSO/OIDC/SAML integration.
- Live Langfuse/OpenTelemetry dashboard deployment and UI polish.
- A fresh external real run after the user is ready to test the updated product
  flow end to end.
