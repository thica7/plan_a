# Report Artifact v2 Dual-Layer Design

> Superseded by
> [Hybrid Report Artifact v2 Design](2026-06-21-hybrid-report-artifact-v2-design.md).
> Kept for history only. Do not implement this design as the active plan.

## Status

Draft written after auditing the current `report_md` writer path and
`run-142822d52a1ef51bc2d409f23f40da8f`.

This design supersedes the current "single Markdown report with embedded
section markers" direction. Earlier schema-first and schema-contract work remains
useful, but only as input authoring and compatibility machinery. The product
artifact must become dual-layer at the data model, API, frontend, export, QA,
and release-gate boundaries.

## Problem

The current project still treats `report_md` as the only report product:

- `RunDetail.report_md` is the frontend-visible report.
- `ReportVersionRecord.report_md` is the enterprise report version.
- `build_enterprise_projection()` projects from `detail.report_md`.
- The frontend report studio reads only `detail.report_md`.
- Writer repair, publication contract, release gate, report quality, and final
  QA all inspect the same Markdown.

That means one Markdown body is carrying conflicting responsibilities:

- core business analysis for readers;
- support appendix;
- source appendix;
- QA checklist;
- claim-risk audit;
- RAG gap notes;
- repair and generation metadata.

This is why fixes keep turning into patches. A marker fix prevents one parser
from damaging sections, but another quality path still sees support checklist
lines as business claims. A publication contract can pass while release gate
blocks. A final QA message can report zero issues while the enterprise release
gate records blockers. The architecture lets these disagreements exist.

## Goal

Create a first-class Report Artifact v2 with a hybrid evidence-to-report
pipeline:

1. Convert evidence into structured claim cards before report writing.
2. Convert cross-competitor claims into structured decision cards before report
   writing.
3. Feed section briefs, not raw source soup, to the natural segment writer.
4. Store and serve the core report separately from support appendix and audit
   material.
5. Make release gate evaluate core business claims and decision cards, not
   support checklist text.
6. Keep complete source, card, QA, repair, and traceability data available for
   support/audit review.
7. Keep legacy runs readable through a compatibility adapter.
8. Move current writer Markdown-hardening patches out of the main path once the
   hybrid artifact is authoritative.

## Non-Goals

- Do not redesign raw collection, crawling, or source identity semantics in this
  project.
- Do not try to solve pricing/persona fact normalization in this spec. The new
  artifact should expose where those upstream facts are mixed, but the deeper
  upstream schema work is a later project.
- Do not make the writer the owner of facts or recommendations. Analyst-owned
  claim cards and comparator-owned decision cards are the reasoning boundary;
  writer output is narrative expression over those cards.
- Do not make the frontend a full report editor. It only needs reader tabs,
  source trace, export choices, and quality visibility.
- Do not delete legacy Markdown support immediately. Existing runs and report
  versions must continue to render.

## Current Writer Patch Inventory

The current writer has several layers that exist because the final product is
still a single Markdown string.

### Keep As Foundation

These pieces remain valuable in Report Artifact v2:

- `writer/evidence_pack.py`
  - Keep the Writer Evidence Pack. It is the right input compaction boundary.
- `writer/structured_report.py`
  - Keep and extend the typed report model. It already has `core` and `support`
    fields.
- `writer/structured_validation.py`
  - Keep typed validation for structured claims, source IDs, confidence, and
    evidence roles.
- `writer/structured_renderer.py`
  - Keep as a deterministic renderer, but split rendering into core/support
    outputs instead of rendering one combined Markdown.
- `writer/structured_hygiene.py`
  - Keep source-token validation helpers.
- `business_intel/report_sections.py`
  - Keep as legacy compatibility and markdown section indexing for old runs.
    It should not be the primary Report Artifact v2 boundary.

### Move To Legacy Or Compatibility

These should stop being main-path correctness mechanisms after dual-layer
storage exists:

- `writer/publication_contract.py`
  - Current job: prove one Markdown body has correct section markers, no English
    structural headings in zh-CN reports, valid source IDs, and core-before-
    support ordering.
  - V2 job: validate rendered legacy Markdown exports only. Main-path validation
    should be artifact schema validation.
- `writer/repair.py::replace_markdown_section()`
  - Current job: replace a section inside one Markdown body without corrupting
    markers.
  - V2 job: legacy report repair only. Main-path repair should replace
    `core.sections[key]`, `support.sections[key]`, or `audit.events`.
- `writer/repair.py::_restore_canonical_section_order()`
  - Current job: reorder H2 sections after a Markdown repair.
  - V2 job: not needed on the main path because artifact section order is a
    structured list.
- `writer/quality_preflight.py`
  - Current job: parse Markdown H2s to detect missing/duplicate core sections
    and support-before-core damage.
  - V2 job: legacy adapter check only. Main-path preflight should inspect
    `core_report.sections`, not Markdown headings.
- `business_intel/report_sections.py::report_section_marker()`
  - Current job: hidden marker comments simulate layers in Markdown.
  - V2 job: export annotation only, not storage truth.

### Retire From Main Path

These are the clearest symptoms of single-Markdown architecture and should not
be used for Report Artifact v2:

- `logic.py::_ensure_report_required_sections()`
  - It backfills missing core/support sections into Markdown and can introduce
    boilerplate, checklist text, and support material into the reader report.
- `logic.py::_backfill_*_section()`
  - Especially support/audit backfills such as scenario checklist, claim risk,
    RAG gap fill, source quality, and evidence appendix. These should become
    structured support/audit payload builders, not Markdown injected into the
    core report.
- `logic.py::_ensure_report_claim_citations()`
  - It heuristically appends citations based on line content. V2 should cite
    claims at the structured claim level before rendering. The renderer should
    only print known source IDs.
- `logic.py::_repair_report_source_token()`
  - It rewrites invalid source tokens by guessing from dimensions or line text.
    V2 should reject invalid source IDs in the structured artifact.
- `logic.py::_harden_schema_contract_report_markdown()`
  - This is a Markdown hardening pass. V2 hardening should validate artifact
    fields before any Markdown is rendered.
- `logic.py::_repair_schema_contract_publication_issues()`
  - It asks the LLM to rewrite sections to satisfy Markdown publication rules.
    V2 should repair typed sections or fail closed.
- Support/checklist text inside `report_md`
  - Scenario QA, claim-risk audit, evidence appendix, next collection, and
    RAG gaps should not be concatenated into the reader report by default.

### Keep Temporarily During Migration

These pieces can remain while V2 is rolled out:

- `assembler.py::assemble_report_fragments()`
  - Keep to assemble legacy schema-contract Markdown fragments until V2 writer
    emits `ReportArtifact` directly.
- `segment_contract.py`
  - Keep as a prompt/segment discipline mechanism while authoring still uses
    natural segment Markdown. It should not define final storage shape.
- `publication_contract.py`
  - Keep as a compatibility gate for legacy Markdown exports.
- `ReportView` and `RunReportReviewStudio`
  - Keep for legacy run rendering, but add V2 tabs and prefer artifact fields
    when present.

## Target Model

Add a `ReportArtifactV2` model.

Conceptual shape:

```text
ReportArtifactV2
  artifact_version: "2"
  run_id
  workspace_id
  project_id
  topic
  output_language
  competitors[]
  dimensions[]
  claim_cards[]
  decision_cards[]
  section_briefs[]
  core_report
  support_appendix
  audit_log
  structured_report
  quality_result
  render_cache
```

### Claim Cards

`claim_cards` are analyst-owned atomic judgments derived from evidence.

They are not final prose and they are not writer-authored. They describe what
the system is allowed to say.

Each claim card includes:

- stable card ID;
- competitor;
- dimension;
- claim text;
- source IDs;
- confidence;
- evidence role;
- evidence strength;
- conflict notes;
- applicability scope;
- known caveats;
- producing agent and timestamp.

Claim cards may be rendered in the support appendix, but they are not stored
only as support prose. Core report claims should reference claim card IDs so the
reader-facing narrative can be audited back to the structured judgment.

### Decision Cards

`decision_cards` are comparator-owned cross-competitor judgments derived from
claim cards.

They include:

- recommendation;
- recommendation strength, such as strong, tentative, or watchlist;
- winning and losing competitors by decision context;
- why-not alternatives;
- risk-adjusted rationale;
- evidence gaps that limit the decision;
- source claim card IDs;
- confidence and conflict notes.

Writer may not change the recommendation posture unless comparator emits a new
decision card or the repair path explicitly downgrades the recommendation.

### Section Briefs

`section_briefs` are writer-facing contracts generated from claim and decision
cards.

Each brief includes:

- target report section;
- required claim card IDs;
- required decision card IDs;
- questions the section must answer;
- forbidden overclaims;
- required caveats;
- citation requirements;
- output language and tone constraints.

The natural segment writer consumes section briefs. It does not receive
unbounded raw source dumps as its primary authority.

### Core Report

`core_report` is the reader-facing business report.

It includes:

- executive summary;
- decision summary;
- competitive findings;
- user review themes;
- competitor deep dives;
- side-by-side decision matrix;
- SWOT;
- battlecard;
- community triangulation when material.

It excludes:

- source appendix tables;
- QA checklist;
- RAG gap queue;
- claim validation logs;
- repair history;
- "how this report was generated" notes.

Core claims must carry:

- text;
- source IDs;
- claim card IDs;
- decision card IDs when applicable;
- confidence;
- evidence role;
- claim kind;
- optional risk note.

### Support Appendix

`support_appendix` is evidence-facing but still reader-visible on a separate tab.

It includes:

- source quality summary;
- user research evidence summary;
- confidence notes;
- RAG gaps;
- next collection plan;
- source appendix rows.

Support appendix entries are not release-gate business claims by default. If a
support entry is promoted into a core claim, it must be copied into `core_report`
with explicit source IDs and confidence.

The support appendix should render claim cards, decision cards, and section
brief provenance in reader-friendly tables. These tables are audit/support
material; the authoritative card data remains on the artifact itself.

### Audit Log

`audit_log` is operational traceability.

It includes:

- QA findings;
- release gate findings;
- redo decisions;
- repair decisions;
- writer mode and evidence-pack metrics;
- publication/export validation;
- final quality result.

Audit entries are not report claims. They must not be scanned by core claim
quality rules.

### Structured Report

`structured_report` keeps the existing typed content object, extended or wrapped
as needed during migration.

It is no longer the final reasoning boundary. Claim cards and decision cards are
the reasoning boundary; `structured_report` is an optional authoring/rendering
object used to build `core_report` and `support_appendix` while the writer is
migrating.

### Quality Result

`quality_result` is the single final quality account for the artifact.

It includes:

- execution status;
- publication status;
- release status;
- blocker count;
- warn count;
- issue count;
- readiness score;
- issue list;
- quality source/version;
- created_at.

Only this object may drive final run status, report version status, release gate
display, and revision convergence. There must not be separate conflicting
counts in QA messages, enterprise projection, and revision records.

### Render Cache

`render_cache` stores deterministic rendered Markdown/HTML strings:

- `core_markdown`;
- `support_markdown`;
- `audit_markdown`;
- `full_markdown`;

The cache is derived data. It can be regenerated from the structured artifact.
It exists for UI and export speed, not as the source of truth.

## Persistence

### SQLite Run Journal

`runs.detail_json` already stores `RunDetail`. Add optional fields to
`RunDetail`:

- `report_artifact: ReportArtifactV2 | None`
- keep `report_md` for legacy and compatibility.

For V2 runs:

- `detail.report_artifact` is authoritative.
- `detail.report_md` is a derived compatibility value equal to
  `render_cache.full_markdown` or `render_cache.core_markdown` depending on the
  legacy UI route.

### Enterprise Report Version

Extend `ReportVersionRecord`:

- `core_report_md: str = ""`
- `support_appendix_md: str = ""`
- `audit_log_md: str = ""`
- `full_report_md: str = ""`
- `report_artifact: dict[str, Any] = {}`
- keep `report_md` as a legacy alias.

For new versions:

- `report_md` should equal `full_report_md` for compatibility.
- release gate should read `core_report_md` plus structured core claims.
- support/audit metadata should live in artifact fields, not only inside
  `quality_metadata`.

### Postgres Migration

Add nullable columns to `report_versions`:

- `core_report_md TEXT`
- `support_appendix_md TEXT`
- `audit_log_md TEXT`
- `full_report_md TEXT`
- `report_artifact JSONB`

Migration rule:

- Existing rows get `full_report_md = report_md`.
- Existing rows get empty `core_report_md`, `support_appendix_md`,
  `audit_log_md`, and `report_artifact = { "artifact_version": "legacy" }`.
- Legacy rows are adapted at read time by parsing `report_md`.

## Writer Flow

### Main Path

1. Build Writer Evidence Pack.
2. Analyst layer converts evidence groups into claim cards.
3. Comparator layer converts claim cards into decision cards.
4. Writer planner converts claim and decision cards into section briefs.
5. Natural segment writer writes section prose from section briefs.
6. Deterministic assembler builds `ReportArtifactV2` with cards, briefs,
   core/support/audit layers, and render caches.
7. Validate artifact schema.
8. Validate core claims against claim cards, decision cards, and allowed source
   IDs.
9. Store artifact on `RunDetail` and project to `ReportVersionRecord`.
10. Emit a single quality result.

The writer should not use one combined Markdown document as the internal repair
surface.

During migration, step 5 may still use the current schema-contract segmented
Markdown writer. That is an authoring detail only. The generated Markdown must
be promoted into `ReportArtifactV2`, and the artifact's cards and briefs remain
the source of truth for facts, recommendations, citations, and repair scope.

### Repair Path

Repair targets are artifact paths:

- `claim_cards[claim-card-id]`
- `decision_cards[decision-card-id]`
- `section_briefs[section-key]`
- `core_report.sections.executive_summary`
- `core_report.sections.competitor_deep_dives[Cursor]`
- `support_appendix.source_quality`
- `audit_log.quality_result`

Repair must not target `report_md.line[n]` on V2 artifacts.

If a repair changes only support/audit material, it must not rewrite the core
report. If a repair changes one core section, it must not rewrite unrelated
core sections unless the quality result explicitly says the whole core is
invalid.

If a repair is about evidence strength, factual support, pricing facts, persona
signals, or recommendation drift, it must repair or regenerate the relevant
claim cards or decision cards first. The writer may then regenerate only the
affected section brief and section prose.

### Redo Convergence

After redo:

- compute quality result on the candidate artifact;
- compare against previous quality result;
- if blocker/warn count increases without an explicit accepted tradeoff, keep
  the previous artifact and store the candidate as a failed repair attempt in
  `audit_log`.

This directly prevents the observed pattern where a report goes from 6 issues
to 13 or 14 and still replaces the previous report.

## QA And Release Gate

### Scope Rules

Core quality rules inspect:

- claim cards referenced by the core report;
- decision cards referenced by the core report;
- `core_report.claims`;
- `core_report.sections`;
- core rendered text only when needed for readability checks.

Support rules inspect:

- unreferenced claim and decision cards;
- section brief coverage;
- source appendix completeness;
- RAG gaps;
- next collection;
- confidence notes.

Audit rules inspect:

- final quality accounting consistency;
- repair/redo traceability;
- event/revision consistency.

Release gate must not scan support checklist or audit entries as strong
business conclusions.

### Single Quality Account

Only `ReportArtifactV2.quality_result` can determine:

- run status;
- report version release status;
- revision `issue_count_after`;
- frontend quality badges;
- approval workflow blockers.

Existing places that compute or copy separate issue counts must read from this
object or become intermediate diagnostics.

## Frontend

Run report view should prefer `detail.report_artifact` when present.

Add report tabs:

- `Report`: core report only.
- `Evidence`: support appendix and source trace.
- `QA`: quality result, blockers, warnings, redo attempts.
- `Audit`: event/revision/repair history.

Legacy runs:

- If `report_artifact` is absent, current Markdown reader remains available.
- A compatibility parser may split legacy `report_md` into best-effort sections,
  but the UI must label it as legacy.

The default first screen should be the core report, not the audit/support layer.

## Export

Export modes:

- `core_markdown`: reader-facing report.
- `full_markdown`: core + support + audit.
- `support_markdown`: evidence appendix.
- `audit_json`: machine-readable audit artifact.

Existing export endpoints may keep returning Markdown by default, but should add
an explicit `scope` parameter.

## Compatibility

Old runs and report versions continue to work.

Compatibility adapter:

- reads legacy `report_md`;
- builds a best-effort artifact with `artifact_version = "legacy"`;
- classifies sections using `build_report_section_index()`;
- preserves original Markdown under `render_cache.full_markdown`;
- does not claim legacy parsed support/core split is authoritative.

## Implementation Shape

This should be delivered in phases, but as one coherent design:

1. Add claim card, decision card, section brief, V2 artifact schema models, and
   compatibility adapter.
2. Add deterministic card builders that can derive initial cards from the
   current evidence pack, competitor knowledge, and comparison matrix.
3. Add section brief builder that converts cards into writer-facing section
   contracts.
4. Add persistence fields to run detail and report version models.
5. Add Postgres migration and store support for artifact/card data.
6. Change enterprise projection to write V2 fields.
7. Change writer to consume section briefs, emit/store V2 artifact, and keep
   `report_md` derived.
8. Change release gate and quality accounting to read core artifact plus claim
   and decision cards plus single quality result.
9. Add frontend tabs and export scopes, including support views for cards.
10. Move old Markdown hardening and repair paths behind legacy guards.

## Acceptance Criteria

- New real runs have `detail.report_artifact.artifact_version == "2"`.
- New real runs have non-empty `claim_cards`, `decision_cards`, and
  `section_briefs`.
- `detail.report_md` is derived, not the authoritative report product.
- ReportVersionRecord stores core/support/audit/full fields.
- ReportVersionRecord stores the artifact with cards and briefs.
- Writer section prose references claim or decision cards for material business
  claims.
- Writer cannot change recommendation posture unless the relevant decision card
  changes or is explicitly downgraded.
- Release gate blockers cannot be produced from support checklist lines.
- Release gate blockers can be produced from unsupported core claims or weak
  decision cards.
- Final QA, enterprise projection, revision records, and run status all report
  the same issue counts.
- Writer repair targets cards, briefs, or artifact paths, not Markdown lines,
  for V2 reports.
- Frontend opens on the core report tab and exposes support/QA/audit separately.
- Frontend Evidence tab exposes claim cards and decision cards as support
  material.
- Exports can produce core-only and full-audit reports.
- Legacy runs still render.
- Current marker/section-order fixes are either removed from V2 main path or
  explicitly guarded as legacy/export validation.

## Risks

- This is larger than another writer patch. It touches schema, persistence,
  enterprise projection, release gate, frontend, exports, and tests.
- During migration, both legacy and V2 rendering paths will exist. Tests must
  make the boundary explicit.
- If writer still produces only natural Markdown fragments, an adapter must
  promote those fragments into artifact fields deterministically.

## Design Decision

Proceed with Report Artifact v2.

Proceed with the hybrid Report Artifact v2 architecture.

The current schema-contract segmented Markdown writer may remain as an authoring
implementation detail during transition, but it must stop being the reasoning,
storage, QA, release, and frontend product boundary. Claim cards and decision
cards are the reasoning boundary. Report Artifact v2 is the product/publication
boundary. Markdown is only rendered output.
