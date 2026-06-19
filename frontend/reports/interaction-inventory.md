# Frontend Interaction Authenticity Inventory

Date: 2026-06-10
Gate: Interaction Authenticity Gate v2

## Verification

```powershell
corepack pnpm --pm-on-fail=ignore --dir frontend verify:interactions
corepack pnpm --pm-on-fail=ignore --dir frontend test
```

Latest local result:

- `verify:interactions`: passed.
- Full frontend test suite: 13 files, 54 tests passed.
- Production build: passed.
- Interaction audit: 0 errors, 83 transitional warnings.

## Delivered

| Area | Status |
|---|---|
| DOM test harness | Added via Vitest jsdom setup |
| `ActionButton` | Tested; rejects missing handlers, missing disabled reasons, and icon-only controls without names |
| `ActionLink` | Tested; rejects empty, `#`, and `javascript:` style fake destinations |
| AST audit | Added with negative fixture tests |
| `audit:interactions` | Added to `frontend/package.json` |
| `verify:interactions` | Added to `frontend/package.json` |
| Topbar | Tested; menu is real, help/notifications are disabled with reasons, research link routes to `/` |
| Workbench view switcher | Migrated to `ActionButton`; tested as real local view state |
| New Run readiness | Tested for disabled reason, submit loading lockout, and HITL local toggle |
| Report release/export | Migrated to `ActionButton`; tested for real callbacks, blockers, and duplicate-action lockout |

## Inventory

| Surface | File | Control | Classification | Target |
|---|---|---|---|---|
| App shell | `frontend/src/components/app-shell/Topbar.tsx` | Mobile navigation | local | `onMenuClick` |
| App shell | `frontend/src/components/app-shell/Topbar.tsx` | AI Research | route | `/` |
| App shell | `frontend/src/components/app-shell/Topbar.tsx` | Workspace/product switchers | disabled | Demo unavailable state |
| App shell | `frontend/src/components/app-shell/Topbar.tsx` | Theme/locale toggles | local | Zustand stores |
| New Run | `frontend/src/features/new-run/RunReadinessRail.tsx` | Start Run | submit | Run builder form |
| New Run | `frontend/src/features/new-run/RunReadinessRail.tsx` | Cost details | disabled | Demo unavailable state |
| Workbench | `frontend/src/features/workbench/ViewSwitcher.tsx` | View tabs | toggle | `onChange(view)` |
| Reports | `frontend/src/features/workbench/ReportReleasePanel.tsx` | Start review | mutation | `onReportAction("start_review")` |
| Reports | `frontend/src/features/workbench/ReportReleasePanel.tsx` | Approve/reject | mutation | `onReportAction("approve" / "reject")` |
| Reports | `frontend/src/features/workbench/ReportReleasePanel.tsx` | Publish | mutation | `onReportAction("publish")` |
| Reports | `frontend/src/features/workbench/ReportReleasePanel.tsx` | Export Markdown/HTML/CSV | download | `onExport(format)` |

## Remaining Risks

1. New Run readiness still needs the full blocker precedence from the spec: submitting, runtime unavailable, quota, missing topic, missing/invalid competitors, missing dimensions, source policy, HITL conflict, ready.
2. The audit currently allows legacy native controls by explicit file-level entries. These warnings expire on 2026-07-15 and should be reduced by migration or per-control metadata.
3. Frontend permission availability is not yet unified with every backend policy decision.
4. React Router v7 future-flag warnings appear during tests; they do not fail the suite.
