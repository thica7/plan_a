# Bilingual Output Language Contract Design

Date: 2026-06-10
Status: Approved direction, pending implementation plan

## Objective

Make the product bilingual with Simplified Chinese as the default output language and English as an explicit option. The language choice must apply to generated content, not only frontend chrome. Reports, agent-facing summaries, QA findings, release guidance, demo output, fallback output, and exported report bodies should follow the selected language while preserving citations, URLs, product names, company names, and technical identifiers.

## Current Problem

The current app has a frontend i18n store, but generated content is English-first:

- The frontend default locale is `en-US`.
- `RunCreateRequest` has no `locale` or `output_language` field.
- New Run submits topic, competitors, dimensions, scenario, and execution mode, but does not submit language.
- Writer, planner, collector, analyst, comparator, QA, demo, and fallback prompts are English.
- Deterministic report headings and report repair sections are English.
- Demo reports and starter presets are English.
- Report export returns the existing `report_md` unchanged, so export inherits whatever language was generated.

Because language is not modeled as durable run state, the backend cannot consistently honor Chinese output even if the frontend UI is translated.

## Goals

- Default the UI and generated content to `zh-CN`.
- Allow users to choose `zh-CN` or `en-US` for each run.
- Persist the selected output language on run and report records.
- Keep existing citation format unchanged: `[source:ID]`.
- Keep company names, product names, URLs, source IDs, model names, framework names, and standards such as SOC 2 or ISO/IEC in their original form unless user input already localizes them.
- Ensure demo, real LLM, fallback, HITL redo, manual revision guidance, QA summaries, release gate recommendations, and report exports are language-consistent.
- Avoid translating stored source evidence itself. Source text remains source text; generated summaries and analysis should follow the selected output language.

## Non-Goals

- Full localization of every internal developer log.
- Machine-translating historical reports automatically during this change.
- Translating third-party source content, quoted evidence, URLs, source IDs, or legal/technical standard names.
- Rewriting every existing English test fixture unless it validates user-facing generated output.

## Language Model

Use a small explicit enum shared by backend and frontend:

```text
output_language = "zh-CN" | "en-US"
```

Default:

```text
zh-CN
```

`zh-CN` means Simplified Chinese output for user-facing generated content. It does not require translating proper nouns or citation IDs.

`en-US` means English output using the current report style.

## Data Flow

1. Frontend initializes UI locale to `zh-CN`.
2. New Run shows a report language control defaulting to the current UI locale, with `zh-CN` selected by default.
3. New Run sends `output_language` in `RunCreateRequest`.
4. Backend validates and stores `output_language` in `RunDetail`.
5. Enterprise projection copies `output_language` into `ReportVersionRecord.quality_metadata` or a typed field if the schema change is acceptable.
6. Agent prompts receive a single language instruction from a shared helper.
7. Deterministic templates choose localized headings and sentence fragments through the same helper.
8. Report export returns the already localized `report_md`; metadata records the selected language.

## Backend Schema Changes

Add `OutputLanguage` type:

```python
OutputLanguage = Literal["zh-CN", "en-US"]
```

Add to `RunCreateRequest`:

```python
output_language: OutputLanguage = "zh-CN"
```

Add to `RunSummary` and `RunDetail`:

```python
output_language: OutputLanguage = "zh-CN"
```

Include output language in active run duplicate fingerprint so a Chinese and English run with the same inputs are not treated as duplicates.

For `ReportVersionRecord`, prefer a typed field if migration risk is low:

```python
output_language: OutputLanguage = "zh-CN"
```

If broad schema churn is risky, store it in `quality_metadata["output_language"]` first and promote to a typed field in a later migration.

## Backend Language Helper

Create a focused helper, for example:

```text
backend/packages/i18n/language.py
```

Responsibilities:

- Normalize requested language with safe default `zh-CN`.
- Provide `language_instruction(output_language)`.
- Provide report section labels.
- Provide short deterministic phrases used by fallback/demo/report repair code.
- Provide tests for normalization and labels.

Example instruction for Chinese:

```text
Use Simplified Chinese for all user-facing generated analysis, report headings, recommendations, QA explanations, and caveats. Preserve product names, company names, URLs, source IDs, citation tokens like [source:ID], model names, framework names, and formal standards in their original form when appropriate. Do not translate source IDs or citation syntax.
```

Example instruction for English:

```text
Use English for all user-facing generated analysis, report headings, recommendations, QA explanations, and caveats. Preserve source citation syntax exactly.
```

## Agent Prompt Changes

Inject the language instruction into every LLM-facing agent that creates user-facing content:

- Planner: planning notes, competitor discovery rationale.
- Collector: source summaries.
- Analyst: structured knowledge claims.
- Comparator: matrix summary.
- Reflector: gaps and confidence notes.
- Writer: report body and headings.
- QA: findings, redo rationale, report QA sections.
- Runtime/manual revision: reviewer-facing report rewrite instructions.

The writer prompt must explicitly require the selected language for:

- Headings.
- Recommendation language.
- Caveats and uncertainty statements.
- Source quality explanation.
- Next validation tasks.

Structured JSON keys remain English because they are schema fields. String values inside those fields should follow `output_language` when user-facing.

## Deterministic Template Changes

Localize deterministic output paths:

- `_demo_report`
- `_fallback_report_markdown`
- `_ensure_report_required_sections`
- `_writer_required_sections`
- `_writer_layer_label`
- `_writer_layer_context`
- source quality sections
- scenario checklist
- claim validation sections
- next collection plan
- evidence appendix heading
- release repair sections
- release gate recommendations that are displayed to end users

The implementation should avoid scattering `if output_language == ...` blocks through large files. Prefer a small dictionary/helper for labels and phrases, then call it from existing functions.

## Frontend Changes

Default locale:

```text
zh-CN
```

New Run:

- Add a report language segmented control or select.
- Default to `zh-CN`.
- Keep it independent from UI locale after initialization.
- Submit `output_language` in create run and workflow start calls.
- Show selected output language in Run Detail header or metadata strip.

Starter presets:

- Provide Chinese default topic and labels for the Chinese UI.
- Preserve English product names.
- When UI is Chinese, starter topics should be Chinese, for example:
  - `AI 编程助手竞品战报`
  - `企业 AI 搜索工作流与替换风险`
  - `大模型应用平台市场格局`

Frontend generated labels and empty states should continue using the existing i18n store.

## Backward Compatibility

Existing saved runs without `output_language` should be treated as `zh-CN` only if they are newly generated after this change. Historical records should preserve their existing text. When reading old records:

- Missing `output_language` defaults to `en-US` if the report body appears English and already exists.
- Missing `output_language` defaults to `zh-CN` for new create requests and empty reports.

This prevents old English reports from being mislabeled as Chinese.

## Testing Strategy

Backend unit tests:

- `RunCreateRequest` defaults `output_language` to `zh-CN`.
- Run detail persists `output_language`.
- Duplicate fingerprint includes `output_language`.
- Writer language instruction is included for `zh-CN` and `en-US`.
- Demo report headings are Chinese for `zh-CN` and English for `en-US`.
- Fallback report headings are Chinese for `zh-CN` and English for `en-US`.
- Citation tokens remain unchanged in Chinese output.
- Report projection carries language metadata.

Frontend tests:

- Initial UI locale is `zh-CN`.
- New Run submits `output_language: "zh-CN"` by default.
- User can select `en-US`.
- Run detail displays selected language.

Integration smoke:

- Create a demo Chinese run and assert report contains Chinese headings such as `执行摘要` or `来源质量与覆盖`.
- Create a demo English run and assert report contains `Executive Summary`.
- Ensure `[source:...]` survives both paths.

## Acceptance Criteria

- A first-time user sees Chinese UI by default.
- A default New Run produces a Simplified Chinese report.
- An English New Run produces an English report.
- Real LLM writer and deterministic fallback paths both honor the selected language.
- Demo mode honors the selected language.
- Report exports do not alter citation syntax.
- English fixed text no longer leaks into Chinese reports except allowed proper nouns, technical terms, URLs, source IDs, and schema identifiers.

## Implementation Boundaries

Keep the first implementation focused on the run/report path. Do not attempt to fully localize:

- Internal traces intended only for developers.
- Stored source evidence.
- Historical reports.
- Every existing backend exception string.

After the run/report path is stable, a follow-up can localize deeper enterprise dashboard findings and governance details.
