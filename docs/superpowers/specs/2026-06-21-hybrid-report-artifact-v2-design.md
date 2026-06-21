# Hybrid Report Artifact v2 Design

> Superseded by
> [Card-Native Report Artifact v2 Design](2026-06-21-card-native-report-artifact-v2-design.md).
> Kept for history only. Do not implement this design as the active plan.

## Status

Historical design. Superseded by
`docs/superpowers/specs/2026-06-21-card-native-report-artifact-v2-design.md`.
This document previously superseded
`docs/superpowers/specs/2026-06-21-report-artifact-v2-dual-layer-design.md`.

The older dual-layer design correctly identified the product boundary problem,
but it still read like a compromise around the current schema-contract Markdown
writer. This design makes the higher-level architecture explicit:

```text
Evidence Pack
  -> Claim Cards
  -> Decision Cards
  -> Section Briefs
  -> Natural Segment Writer
  -> Deterministic Assembler
  -> Report Artifact v2
```

## Problem

The current system asks writer-side code to do too many jobs at once:

- interpret raw sources and evidence pack context;
- infer claims;
- infer recommendations;
- write readable report prose;
- preserve section structure;
- preserve citations;
- separate reader-facing content from support and audit material;
- survive redo without drifting recommendations.

This is why fixes keep becoming Markdown patches. Marker repair, heading repair,
publication contract repair, section backfill, and citation repair are all
trying to recover structure after the writer has already been allowed to blur
facts, judgments, prose, and support material into one `report_md` string.

The durable boundary should not be pure typed report JSON, because that makes
the report stiff and limits prose quality. It should also not be free-form
natural segments, because that lets recommendations drift and makes QA depend
on fragile text parsing.

## Goal

Build a hybrid report pipeline:

1. Analyst-owned claim cards capture atomic facts, evidence strength, caveats,
   conflicts, and source IDs.
2. Comparator-owned decision cards capture recommendation posture, why-not
   alternatives, risk adjustment, and the claim cards behind each decision.
3. Writer-facing section briefs define exactly what each natural segment may
   say and must answer.
4. Natural segment writer produces readable business prose from section briefs.
5. Deterministic assembler owns headings, section order, citation hygiene,
   core/support/audit separation, and final render caches.
6. Report Artifact v2 stores cards, briefs, core report, support appendix,
   audit log, quality result, and derived Markdown caches.

## Non-Goals

- Do not rewrite crawler/fetch/source identity behavior in this project.
- Do not make the writer produce or own final facts and recommendations.
- Do not force final reports to be pure typed JSON prose.
- Do not remove legacy `report_md` compatibility immediately.
- Do not solve every upstream pricing/persona normalization issue. The card
  layer should expose weak or mixed evidence cleanly so those issues can be
  addressed next.

## Architecture

### Data Flow

```text
RawSource / KB / ComparisonMatrix
  -> WriterEvidencePack
  -> ClaimCardBuilder
  -> DecisionCardBuilder
  -> SectionBriefBuilder
  -> NaturalSegmentWriter
  -> ArtifactAssembler
  -> ReportArtifactV2
```

Current project reality: the writer already has a Writer Evidence Pack and a
schema-contract segmented Markdown writer. The first implementation should not
throw that away. It should add the card/brief layer before writer authoring and
make `ReportArtifactV2` the only publication product boundary.

### Ownership

- Collector owns raw sources, normalized source fields, fetch policy, and source
  identity.
- Analyst owns claim cards.
- Comparator owns decision cards.
- Writer owns natural section prose from section briefs.
- Assembler owns final structure, section markers, layer separation, and render
  caches.
- QA/release gate owns validation against cards, briefs, core prose, and support
  material by explicit scope.

### Why This Is Not The Old Typed JSON Writer

Claim cards and decision cards are structured JSON/Pydantic objects, but they
are not the final report. They are the reasoning substrate.

Old typed report JSON tried to make the LLM fill the report shape directly:

```text
executive_summary
user_review_themes
swot
battlecard
decision_matrix
```

Hybrid cards instead describe what can be said:

```text
claim: fact or evidence gap
decision: recommendation and why-not alternatives
brief: what a section must answer
```

The writer then writes natural prose from those constraints. That preserves the
prose upside of the stable natural writer while preventing the writer from
inventing facts or changing recommendations.

## Models

### ClaimCard

Analyst-owned atomic judgment.

Required fields:

- `id`
- `competitor`
- `dimension`
- `claim`
- `source_ids`
- `confidence`
- `evidence_role`
- `evidence_strength`
- `conflict_notes`
- `applicability_scope`
- `caveats`
- `produced_by`
- `created_at`

Rules:

- Non-gap claim cards require at least one source ID.
- Evidence-gap claim cards may have no source IDs.
- Confidence must stay in `[0, 1]`.
- Claim cards do not contain Markdown citation tokens.
- A strong claim cannot be based only on weak/community/simulated evidence.

### DecisionCard

Comparator-owned recommendation judgment.

Required fields:

- `id`
- `decision_type`
- `recommendation`
- `recommendation_strength`
- `winner`
- `alternatives`
- `why_not`
- `rationale`
- `claim_card_ids`
- `confidence`
- `risk_notes`
- `produced_by`
- `created_at`

Rules:

- Every decision card references at least one claim card.
- A strong recommendation requires strong claim-card support.
- If evidence is weak or mixed, recommendation strength must be tentative,
  watchlist, or insufficient evidence.
- Writer cannot change recommendation posture unless the decision card changes.

### SectionBrief

Writer-facing contract.

Required fields:

- `section_key`
- `required_claim_card_ids`
- `required_decision_card_ids`
- `questions`
- `forbidden_overclaims`
- `required_caveats`
- `citation_requirements`
- `output_language`
- `tone`

Rules:

- Every section brief references at least one claim card or decision card.
- Briefs define allowed content; raw source digests are secondary context.
- Writer may add connective prose, but not new facts or new recommendations.

### ReportArtifactV2

Publication/product boundary.

Required top-level fields:

- `artifact_version`
- `run_id`
- `workspace_id`
- `project_id`
- `topic`
- `output_language`
- `competitors`
- `dimensions`
- `claim_cards`
- `decision_cards`
- `section_briefs`
- `core_report`
- `support_appendix`
- `audit_log`
- `quality_result`
- `render_cache`

`core_report` is the reader-facing business report. It references claim and
decision cards.

`support_appendix` renders evidence support, card tables, source quality, RAG
gaps, next collection, and confidence notes. Support material is not scanned as
business claims.

`audit_log` renders operational traceability: QA findings, release gate
findings, redo decisions, repair attempts, writer mode, and quality accounting.

`render_cache` stores derived Markdown strings:

- `core_markdown`
- `support_markdown`
- `audit_markdown`
- `full_markdown`

`report_md` remains a compatibility alias for `full_markdown`, not the source
of truth.

## Writer Behavior

Writer input must be section briefs plus referenced cards. The writer may see
bounded supporting source snippets for context, but cards and briefs outrank raw
snippets.

Writer must:

- answer each section brief's questions;
- cite only sources reachable from referenced claim cards;
- preserve decision-card recommendation posture;
- include caveats required by claim and decision cards;
- write natural, polished prose.

Writer must not:

- create new facts not present in claim cards;
- change recommendation winner or strength;
- hide weak evidence by writing confident prose;
- move support/audit content into the core report.

## Assembler And Publication Contract

Assembler is deterministic. It owns:

- H1/H2/H3 structure;
- section order;
- section markers;
- citation placement;
- core/support/audit layer separation;
- rendered card tables;
- full Markdown export assembly.

The publication contract validates the assembled artifact, not free-form writer
Markdown. For legacy runs it may still validate old Markdown exports.

## QA And Release Gate

Quality scopes are explicit:

- Core rules inspect core prose plus referenced claim and decision cards.
- Support rules inspect support appendix completeness and card/source coverage.
- Audit rules inspect revision, redo, and quality accounting consistency.

Release gate must not scan support checklist or audit rows as strong business
conclusions.

Warnings and blockers must map to one of these repair targets:

- source collection;
- claim card;
- decision card;
- section brief;
- section prose;
- assembler/publication;
- audit/quality accounting.

## Redo And Repair

Redo cannot default to full rewrite.

Routing:

- missing or weak evidence -> collector or analyst claim-card regeneration;
- incorrect factual claim -> claim-card repair;
- recommendation drift or weak recommendation support -> decision-card repair;
- thin or unclear prose with valid cards -> section-brief or section-prose
  repair;
- citation placement, heading, section marker, layer leakage -> assembler
  repair;
- event/revision count mismatch -> audit/quality accounting repair.

If a redo only changes one claim card, only dependent decision cards, briefs,
and sections may change. If a redo changes no decision card, the core
recommendation must not drift.

Candidate artifacts that increase blocker/warn count without an explicit
accepted tradeoff must not replace the previous artifact.

## Frontend

The report view should prefer `detail.report_artifact`.

Tabs:

- `Report`: core report only.
- `Evidence`: support appendix, claim cards, decision cards, source trace.
- `QA`: quality result, warnings, blockers, redo attempts.
- `Audit`: event/revision/repair history.

Default view is `Report`.

Legacy runs without an artifact still render current Markdown and are labeled
legacy.

## Persistence And Export

Store artifact data on run detail and report version:

- `report_artifact`
- `core_report_md`
- `support_appendix_md`
- `audit_log_md`
- `full_report_md`
- legacy `report_md`

Export scopes:

- `core_markdown`
- `support_markdown`
- `audit_json`
- `full_markdown`

## Migration

Phase 1 may derive initial claim cards and decision cards deterministically from
existing evidence pack, raw sources, competitor knowledge, and comparison
matrix. That is acceptable as a bridge.

Phase 1 must still enforce the architecture boundary:

- cards exist before writer prose;
- writer consumes briefs;
- artifact stores cards and briefs;
- release gate validates against cards and core prose;
- Markdown repair paths are legacy guarded.

Future phases can move more card production into analyst/comparator LLM calls
without changing writer, frontend, or release gate contracts.

## Acceptance Criteria

- New real runs have `detail.report_artifact.artifact_version == "2"`.
- New real runs have non-empty claim cards, decision cards, and section briefs.
- Core report claims reference claim card IDs or decision card IDs.
- Support tab displays claim cards and decision cards.
- Writer cannot change recommendation posture without a changed decision card.
- Release gate reads core prose plus cards, not support/audit prose.
- `report_md` is derived from artifact render cache.
- ReportVersionRecord stores core/support/audit/full fields and full artifact.
- Redo targets cards, briefs, section prose, assembler, or audit explicitly.
- Legacy runs still render.

## Superseded Direction

The dual-layer report design is not wrong, but it is incomplete. Dual-layer
core/support/audit separation is now one part of this hybrid architecture. It is
not the main architecture by itself.
