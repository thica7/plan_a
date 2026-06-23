# Schema-First Writer Report Generator Design

Date: 2026-06-19
Status: User-approved design, pending written-spec review

## Purpose

Fix the recurring report-quality failures seen in `run-8a383935ac16727d0d318c2d6bf708db` and `run-e21c7dd3b91808d760c0c261394f24f1` by moving the writer from Markdown-first generation to schema-first generation.

The current segmented writer can now complete reports reliably, but it still lets the model directly author user-facing Markdown. That leaves too much quality-critical behavior to prompt compliance:

- Chinese reports can contain English structural H3/H4 headings.
- `## 战报` can be a generic template instead of a usable battlecard.
- Citations can appear in table headers, headings, appendix rows, or internal notes.
- Internal implementation terms such as `source_registry` or `Segment Evidence Pack JSON` can leak into the report.
- The executive summary can become a fixed system-style four-bullet template instead of a business recommendation.
- Writer-only redo can rewrite whole reports for localized claim warnings and make the report worse.
- Core analysis and support/audit material are still rendered into one Markdown stream without a strong semantic boundary.

The goal is to make the report structure explicit, validated, renderable, and repairable before Markdown exists.

## Non-Goals

- Do not change the frontend report view in this phase.
- Do not add a database migration in the first implementation phase.
- Do not remove the existing Markdown writer path immediately.
- Do not reduce source collection breadth or writer evidence richness.
- Do not weaken source ID validation.
- Do not commit generated reports, DB packages, output artifacts, or local document exports.
- Do not solve community collection quality in this spec; this design controls how collected evidence is written and repaired.

## Design Summary

Introduce a schema-first writer pipeline:

```text
Writer Evidence Pack
  -> Structured Section Writers
  -> StructuredReportAssembler
  -> StructuredReportValidator
  -> MarkdownRenderer
  -> PublicationContract
  -> report_md
```

The LLM no longer owns final Markdown layout. It fills typed section payloads. A deterministic renderer owns headings, section order, table layout, citation placement, appendix shape, and core/support separation.

Existing `report_md` remains the persisted and frontend-visible output. The structured report can initially be stored in trace telemetry or compact `quality_metadata` without requiring a database schema change.

## Architecture

### Existing Components To Keep

- `backend/packages/agents/writer/evidence_pack.py`
  - Continue to build the source-rich Writer Evidence Pack.
  - Continue to split large inputs by section, competitor, source, group, or shard.

- `backend/packages/agents/writer/segment_contract.py`
  - Continue to validate segment ownership and section boundaries while Markdown fallback exists.
  - Later becomes less central for structured JSON sections.

- `backend/packages/agents/writer/assembler.py`
  - Continue to protect current Markdown fallback path.
  - Structured generation gets a new assembler over schema objects.

- `backend/packages/agents/writer/quality_preflight.py`
  - Continue checking final Markdown structure.
  - Add structured-report checks before rendering.

- `backend/packages/agents/writer/repair.py`
  - Keep tiered repair planning.
  - Add structured section repair targets and avoid full rewrite for localized warnings.

### New Components

Add:

- `backend/packages/agents/writer/structured_report.py`
  - Pydantic models for `StructuredReport`, sections, cited text, battlecards, matrices, SWOT, support sections, and metadata.

- `backend/packages/agents/writer/structured_renderer.py`
  - Deterministic Markdown renderer from `StructuredReport`.

- `backend/packages/agents/writer/structured_validation.py`
  - Semantic validation of section completeness, evidence roles, source IDs, battlecard substance, executive-summary quality, and internal-term leakage.

- `backend/packages/agents/writer/publication_contract.py`
  - Final publishability checks over rendered Markdown and structured metadata.

- Tests:
  - `backend/tests/unit/test_writer_structured_report.py`
  - `backend/tests/unit/test_writer_structured_renderer.py`
  - `backend/tests/unit/test_writer_structured_validation.py`
  - `backend/tests/unit/test_writer_publication_contract.py`

## Structured Report Schema

### Top-Level Model

```python
class StructuredReport(BaseModel):
    output_language: str
    topic: str
    competitors: list[str]
    dimensions: list[str]
    core: ReportCore
    support: ReportSupport
    metadata: ReportMetadata
```

### Cited Text Primitive

All factual or analytical claims that need evidence use one primitive:

```python
class CitedText(BaseModel):
    text: str
    source_ids: list[str]
    confidence: Literal["high", "medium", "low"]
    evidence_role: Literal[
        "official_fact",
        "community_signal",
        "simulated_research",
        "inference",
        "evidence_gap",
    ]
```

Rules:

- `text` must not contain Markdown citation tokens.
- `source_ids` must be valid raw source IDs or approved aliases for the current section.
- Strong recommendations cannot rely only on `simulated_research` or low-confidence community signals.
- Evidence gaps may have empty `source_ids` only when explicitly labeled as `evidence_gap`.

### Core Sections

```python
class ReportCore(BaseModel):
    executive_summary: ExecutiveSummarySection
    decision_summary: DecisionSummarySection
    competitive_findings: CompetitiveFindingsSection
    user_review_themes: UserReviewThemesSection
    competitor_deep_dives: list[CompetitorDeepDiveSection]
    decision_matrix: DecisionMatrixSection
    swot: SwotSection
    battlecard: BattlecardSection
    community_triangulation: CommunityTriangulationSection | None = None
```

### Executive Summary

```python
class ExecutiveSummarySection(BaseModel):
    recommendation: CitedText
    risk_adjusted_rationale: CitedText
    competitor_postures: list[CompetitorPosture]
    confidence_boundary: CitedText
    next_actions: list[CitedText]
```

This prevents system-style summaries such as only "core conclusion / decision posture / risk boundary / immediate action." The section must contain a real recommendation, risk-adjusted rationale, competitor-specific posture, and next actions.

If a matrix says a competitor leads one dimension but the report does not recommend that competitor, the distinction must appear in `risk_adjusted_rationale`. Example: "Windsurf has the broadest paper feature coverage, but reliability risk means it is not the risk-adjusted primary recommendation."

### User Review Themes

```python
class UserReviewThemesSection(BaseModel):
    competitor_themes: list[CompetitorUserTheme]
    cross_competitor_patterns: list[CitedText]
    evidence_limits: list[CitedText]

class CompetitorUserTheme(BaseModel):
    competitor: str
    direct_user_signals: list[CitedText]
    simulated_research_signals: list[CitedText]
    adoption_blockers: list[CitedText]
    switching_triggers: list[CitedText]
    evidence_gaps: list[CitedText]
```

Rules:

- Direct community or review signals go into `direct_user_signals`.
- Simulated survey/interview signals go into `simulated_research_signals`.
- The renderer uses localized headings and never lets the LLM produce headings such as `Direct User / Community Signals`.
- If direct user evidence is missing, the section must say so as an evidence gap instead of converting simulated research into real user proof.

### Competitor Deep Dives

```python
class CompetitorDeepDiveSection(BaseModel):
    competitor: str
    positioning: list[CitedText]
    pricing_packaging: list[CitedText]
    feature_capabilities: list[CitedText]
    persona_adoption: list[CitedText]
    community_feedback: list[CitedText]
    competitive_plays: list[CitedText]
    evidence_gaps: list[CitedText]
```

Rules:

- There must be exactly one deep dive per requested competitor, unless the competitor was removed upstream.
- The renderer owns `### <competitor>` and all child headings.
- Missing facts become explicit evidence gaps.

### Decision Matrix

```python
class DecisionMatrixSection(BaseModel):
    dimensions: list[MatrixDimensionRow]
    interpretation: list[CitedText]
    confidence_notes: list[CitedText]

class MatrixDimensionRow(BaseModel):
    dimension: str
    cells: list[MatrixCell]

class MatrixCell(BaseModel):
    competitor: str
    summary: str
    source_ids: list[str]
    confidence: Literal["high", "medium", "low"]
```

The renderer places citations in body cells only, never in table headers.

### SWOT

```python
class SwotSection(BaseModel):
    competitors: list[CompetitorSwot]

class CompetitorSwot(BaseModel):
    competitor: str
    strengths: list[CitedText]
    weaknesses: list[CitedText]
    opportunities: list[CitedText]
    threats: list[CitedText]
```

Every requested competitor must have all four quadrants. Empty quadrants are validation failures unless replaced by explicit evidence gaps.

### Battlecard

```python
class BattlecardSection(BaseModel):
    plays: list[BattlecardPlay]
    evidence_limits: list[CitedText]

class BattlecardPlay(BaseModel):
    competitor: str
    target_buyer: str
    use_when: CitedText
    attack_points: list[CitedText]
    defense_points: list[CitedText]
    likely_objections: list[CitedText]
    rebuttal_talk_tracks: list[CitedText]
    proof_needed_before_external_use: list[CitedText]
```

Rules:

- At least one substantive play per competitor, or a competitor-specific evidence gap explaining why no play can be safely written.
- Generic meta bullets such as "direct battlecard positioning" or "deployment check" are invalid as the whole section.
- Plays must be usable by sales, product marketing, or competitive strategy readers.

### Support Sections

```python
class ReportSupport(BaseModel):
    source_quality: SourceQualitySection
    user_research_evidence: UserResearchEvidenceSection
    rag_gap_fill: RagGapFillSection
    scenario_qa: ScenarioQaSection
    claim_risk: ClaimRiskSection
    next_collection: NextCollectionSection
    evidence_appendix: EvidenceAppendixSection
```

Support sections are rendered after all core sections. They may cite sources but cannot introduce new core recommendations.

### Metadata

```python
class ReportMetadata(BaseModel):
    writer_mode: str
    segment_count: int
    source_count: int
    warnings: list[str]
    structured_report_version: str
```

Metadata is not user-facing. The renderer must not emit implementation keys such as `source_registry`, `allowed_source_ids`, `represented_by`, `Segment Evidence Pack JSON`, `Writer Evidence Pack`, `fact:`, or `signal:`.

## Generation Flow

### Structured Section Writer

Add:

```python
async def _writer_structured_section_json(
    record: RunRecord,
    *,
    segment: dict[str, object],
    section_schema: type[BaseModel],
    allowed_source_ids: set[str],
    timeout_seconds: float,
) -> BaseModel:
```

Prompt contract:

- Return JSON only.
- Match the requested schema.
- Do not write Markdown headings.
- Do not include `[source:...]` tokens inside text fields.
- Put citations only in `source_ids`.
- Use only `allowed_source_ids`.
- Label evidence role accurately.
- Separate official facts, community signals, simulated research, inference, and evidence gaps.

### Structured Assembler

Add:

```python
class StructuredReportAssembler:
    def assemble(section_payloads: Sequence[BaseModel], detail: RunDetail) -> StructuredReport:
        ...
```

Responsibilities:

- Merge section payloads into `StructuredReport`.
- Preserve competitor ownership.
- Enforce one deep dive and one user-theme block per competitor.
- Keep support payloads in `report.support`.
- Keep core payloads in `report.core`.
- Emit telemetry about missing, duplicated, or repaired section payloads.

### Structured Validator

Add:

```python
def validate_structured_report(
    report: StructuredReport,
    *,
    allowed_source_ids: set[str],
    source_strengths: Mapping[str, EvidenceStrengthDecision],
) -> StructuredReportValidation:
    ...
```

Validation checks:

- Required core sections are present.
- Every requested competitor has deep dive, user theme, SWOT, and battlecard coverage or explicit evidence gaps.
- Every `CitedText.source_ids` item is valid.
- Strong recommendation fields have sufficient evidence.
- Simulated research is labeled as simulated.
- Battlecard has substantive plays.
- Executive summary has a real recommendation and risk-adjusted rationale.
- User-facing text does not contain internal implementation terms.
- Text fields do not contain Markdown citation tokens.

### Markdown Renderer

Add:

```python
def render_structured_report(report: StructuredReport) -> str:
    ...
```

Renderer responsibilities:

- Own all H2/H3/H4 headings.
- Use `report_label()` and localized child-heading labels.
- Render citations only where allowed.
- Render table headers without citations.
- Render source appendix rows without unrelated self-citation noise.
- Render all core sections before support sections.
- Do not render metadata.

For `zh-CN`, child headings must be Chinese except product names, technology names, model names, standards, and source IDs.

## Publication Contract

After rendering, run a final contract:

```python
def validate_publication_contract(
    markdown: str,
    structured_report: StructuredReport | None,
    detail: RunDetail,
) -> PublicationContractResult:
    ...
```

Checks:

- No English structural H3/H4 headings in `zh-CN` reports.
- No citations in headings.
- No citations in table header rows.
- No internal implementation terms.
- Battlecard is not template-only.
- Executive summary is not template-only.
- Core sections appear before support sections.
- Evidence appendix format is reader-facing.
- Existing source ID validity still holds.

Publication contract failures produce structured repair targets instead of a generic writer-only full rewrite.

## Repair And Redo Routing

When a structured report exists, writer-only redo should target schema paths:

```text
claim_self_consistency_required
  -> locate CitedText or section
  -> downgrade claim or rewrite one section JSON
  -> re-render Markdown

battlecard_template_only
  -> rewrite core.battlecard only

executive_summary_template_only
  -> rewrite core.executive_summary only

english_structural_heading_in_zh
  -> renderer fix or structured child-heading fix

citation_in_table_header
  -> renderer fix, no LLM call

internal_term_leak
  -> validation failure on text field, rewrite owning section only
```

Full rewrite is allowed only when:

- Multiple required structured core sections are missing.
- JSON schema validation fails repeatedly for multiple essential sections.
- Upstream evidence materially changed.
- No previous structured report exists and Markdown fallback also fails quality gates.

## Compatibility

### Persistence

First implementation keeps `report_md` as the canonical stored report output.

Structured report payload may be recorded as compact metadata:

```python
report_version.quality_metadata["structured_report_summary"]
report_version.quality_metadata["structured_report_validation"]
```

Large full structured payloads should not be stored in metadata unless size-bounded. Full payloads may appear in trace events when safe and compact.

### Fallback

Add a feature flag:

```python
settings.writer_structured_report_enabled = True
```

Default for new real runs should be enabled after Phase 3 tests pass. Existing Markdown writer remains as fallback until several real runs prove stable.

Fallback must be visible in trace:

- `writer_structured_report_failed`
- `writer_markdown_fallback_used`
- failure reason

### Existing Runs

Old runs with only Markdown remain viewable and unchanged.

## Telemetry

Emit trace events:

- `writer_structured_section_generated`
  - section id
  - schema name
  - source count
  - retry count
  - validation status

- `writer_structured_report_assembled`
  - section count
  - competitor coverage
  - missing sections
  - duplicate payloads

- `writer_structured_report_validated`
  - passed
  - issue count
  - issue codes
  - repair targets

- `writer_markdown_rendered`
  - markdown chars
  - core/support section counts
  - citation count

- `writer_publication_contract_validated`
  - passed
  - issue codes
  - deterministic repair count

- `writer_structured_repair_selected`
  - target schema path
  - reason
  - LLM required or deterministic

## Phased Implementation

### Phase 1: Models, Renderer, Validator

Add schema models, renderer, and validator without connecting to the live writer path.

Acceptance:

- Renderer outputs localized headings.
- Renderer keeps citations out of headings and table headers.
- Validator rejects template-only battlecards.
- Validator rejects executive summaries without a risk-adjusted recommendation.
- Validator rejects internal implementation terms in user-facing fields.
- Validator enforces competitor coverage.

### Phase 2: Markdown Adapter For Regression Fixtures

Add a limited adapter:

```python
adapt_markdown_report_to_structured(markdown, detail) -> StructuredReport | PartialStructuredReport
```

This is a transition tool, not the final architecture. It lets tests reproduce current real-run failures without committing full reports.

Acceptance:

- Minimal fixtures representing `run-8a` and `run-e21` failure shapes are detected:
  - English child headings.
  - Template-only battlecard.
  - Citation in table header.
  - Internal implementation leak.
  - Template-like executive summary.
  - Support/audit material mixed into final Markdown.

### Phase 3: JSON Section Writer

Connect structured section writing to the writer pipeline behind the feature flag.

Acceptance:

- Valid JSON section output builds a `StructuredReport`.
- Invalid JSON retries once with schema errors.
- Unknown source IDs fail the section.
- Markdown returned where JSON is expected fails and retries.
- Section failures are scoped.
- Markdown fallback remains available and trace-visible.

### Phase 4: Structured Repair And Release Integration

Route writer-only redo through structured repair when structured report metadata exists.

Acceptance:

- Persona claim warnings target user review themes or claim downgrade fields.
- Battlecard issues target `core.battlecard`.
- Executive summary issues target `core.executive_summary`.
- Citation placement issues are renderer repairs.
- Full rewrite is rare and justified in telemetry.

## Testing Strategy

### Unit Tests

Add focused tests for:

- Schema model validation.
- Renderer localization.
- Renderer citation placement.
- Renderer core/support ordering.
- Structured validator source ID checks.
- Structured validator evidence role checks.
- Structured validator battlecard substance checks.
- Publication contract issue detection.
- Repair target selection.

### Run-Service Tests

Add integration-style unit tests that monkeypatch LLM calls:

- Structured JSON success path.
- Invalid JSON retry.
- Invalid source ID retry/fail.
- Battlecard section retry.
- Executive summary section retry.
- Section repair replaces one structured section and re-renders.
- Markdown fallback is trace-visible.

### Real-Run Verification

After implementation, run a new AI coding agent report and verify:

- `zh-CN` report has no English structural headings.
- `## 战报` contains substantive competitor plays.
- No citation appears in headings or table headers.
- No internal terms appear.
- Executive summary contains risk-adjusted recommendation logic.
- Support sections appear after core analysis.
- Writer-only redo does not full-rewrite for localized claim warnings.

## Acceptance Criteria

- New reports are generated from `StructuredReport` when the feature flag is enabled.
- Markdown renderer owns all report headings and citation placement.
- The seven shared failures from `run-8a` and `run-e21` are represented by tests and blocked by validator or publication contract.
- Existing Markdown writer path remains as explicit fallback.
- No database migration is required for the first phase.
- Existing frontend continues to consume `report_md`.
- Existing source-rich evidence pack behavior is preserved.
- Full rewrite is not used for localized claim warnings when a structured section repair is possible.

## Risks And Mitigations

### Risk: LLM JSON Instability

Mitigation:

- Generate one section at a time.
- Validate with Pydantic.
- Retry once with exact schema errors.
- Keep Markdown fallback until structured path is stable.

### Risk: Schema Becomes Too Free-Text

Mitigation:

- Keep typed section fields.
- Use `CitedText` for evidence-bearing text.
- Make battlecard, matrix, SWOT, and executive summary strongly structured.

### Risk: Structured Payload Too Large For Metadata

Mitigation:

- Store only compact summaries in `quality_metadata`.
- Use trace telemetry for bounded diagnostics.
- Keep `report_md` as persisted output.

### Risk: Renderer Produces Mechanical Reports

Mitigation:

- Allow rich text inside typed fields.
- Keep section-specific LLM writing for substantive content.
- Use schema to control structure, not to flatten analysis.

## Open Implementation Decisions

- Whether to keep full `StructuredReport` only in memory or store a compact version in `quality_metadata`.
- Whether the adapter in Phase 2 should be test-only or kept as a diagnostic helper.
- Whether `settings.writer_structured_report_enabled` should default on immediately after Phase 3 or first run in shadow mode.

These decisions can be resolved during implementation planning without changing the core design.
