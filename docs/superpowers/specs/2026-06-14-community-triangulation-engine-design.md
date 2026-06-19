# Community Triangulation Engine Design

Date: 2026-06-14
Status: Approved design draft
Scope: All dimensions with mixed recommendation semantics

## Problem

Current runs lean too heavily on official pages, customer pages, and synthetic
persona material. Community results sometimes appear in search output, but they
rarely become structured evidence, report claims, or user-review content.

This creates weak behavior in cases such as Cursor pricing:

- If official pages are missing, dynamic, or incomplete, the report often says
  "unknown" even when community and forum sources contain useful consistent
  signals.
- Simulated surveys can fill persona/review sections while real community
  signals remain unused.
- QA treats source type and confidence too tightly together instead of scoring
  whether multiple independent community sources support the same claim.

The goal is to make useful community evidence discoverable, structured,
triangulated, and safely usable in reports.

## Decision

Build a Community Triangulation Engine across all dimensions:

- pricing and limits
- feature behavior and limitations
- persona, adoption, and switching triggers
- review/customer voice themes

The engine uses mixed recommendation semantics:

- Community evidence may affect actual-use conclusions, risk assessment,
  user-evaluation sections, pricing/limit caveats, and risk-adjusted
  recommendations.
- Community evidence must not be presented as an official commitment unless an
  official source also supports the claim.
- Reports must label high-confidence community observations clearly.

## Architecture

The engine is an independent evidence lane that complements official collection.

Pipeline:

1. Community query planner
2. Community source collector
3. Community claim extractor
4. Claim clusterer
5. Triangulation scorer
6. Evidence admission into matrix, review summaries, QA metadata, and writer
   context

The official collector remains the source of official facts. The community lane
supplies observed market behavior, user-reported limits, complaints, praise,
adoption blockers, switching triggers, and contested claims.

Current-project fit for the first implementation:

- Store community semantics in existing `RawSource.source_type` and
  `RawSource.metadata`; do not add a database or DTO migration.
- `ComparisonMatrix` currently has only `winner_by_dimension`, `summary`, and
  `cells`. First implementation should therefore expose
  `community_adjusted_winner` and `risk_adjusted_recommendation` as explicit
  matrix summary/caveat entries and writer context, not as new schema fields.
- Comparator winner voting must treat community sources as community/risk
  signals, not as official evidence-count or official-confidence signals.
- `RawSource` has no first-class author identity. First implementation should
  use domain-level independence plus staff/mod/maintainer text signals; same
  forum different-author independence is deferred until author metadata exists.
- `SearchResult` and `SourceCandidate` may carry `date` or `last_updated`, but
  `RawSource` only has metadata for publication timing. First implementation
  should preserve recency hints when available and avoid hard stale-source
  gates when no parseable date exists.

## Source Types

Community sources should not be collapsed into generic webpage evidence.

New or normalized source types:

- `community_forum`
- `reddit_thread`
- `github_discussion`
- `github_issue`
- `review_site`
- `developer_blog`
- `snippet_only`

Examples:

- Cursor forum usage-limit discussion: `community_forum`
- Reddit post about Cursor pricing confusion: `reddit_thread`
- GitHub Community Copilot billing thread: `github_discussion`
- VS Code Copilot issue: `github_issue`
- G2/Capterra/TrustRadius reviews: `review_site`
- DEV/Medium/Substack hands-on post: `developer_blog`

## Query Planning

Generate community queries for every competitor and dimension. Official gaps
raise priority but are not required for community collection.

Pricing and limits:

- `{competitor} pricing usage limit reddit`
- `{competitor} pricing usage limit forum`
- `{competitor} billing quota GitHub discussion`
- `{competitor} hidden limit cost overage`

Feature behavior:

- `{competitor} context window issue discussion`
- `{competitor} agent mode complaints reddit`
- `{competitor} feature limitation forum`
- `{competitor} bug issue developer workflow`

Persona and adoption:

- `{competitor} user reviews pros cons reddit`
- `{competitor} switched from {competitor} to alternative`
- `{competitor} adoption blockers enterprise developers`
- `{competitor} onboarding workflow fit complaint`

Review and customer voice:

- `{competitor} G2 reviews pros cons`
- `{competitor} Capterra reviews`
- `{competitor} TrustRadius reviews`
- `{competitor} customer complaints alternatives`

Limits for first implementation:

- Up to 3 community queries per competitor and dimension by default.
- Up to 5 search candidates per query.
- Up to 5 evidence items per claim cluster.
- Higher priority for dimensions with official evidence gaps, such as unknown
  pricing, missing limits, or incomplete persona segments.

## Community Claim Extraction

The extractor should prefer concrete claims over vague sentiment.

Good claim examples:

- `Cursor Pro is reported as $20 per month.`
- `Cursor Ultra is reported as $200 per month.`
- `Users report confusion around Cursor usage limits.`
- `GitHub Copilot users report context-window limitations in complex tasks.`
- `Claude Code users report cost spikes under heavy agent usage.`

Weak or ignored claim examples:

- `Pricing is bad.`
- `This tool is amazing.`
- `Is Cursor expensive?`
- `Someone said the limit changed.`

Extracted community claims should include:

- claim text
- competitor
- dimension
- normalized claim kind
- source id
- source type
- date or recency hint
- author/mod/staff signal when available
- evidence excerpt or snippet
- uncertainty and conflict markers

## Claim Clustering

Cluster semantically equivalent claims across sources.

Cluster inputs:

- normalized competitor
- dimension
- claim kind
- normalized value, if any
- semantic similarity of claim text
- recency bucket

Independence checks:

- Different domains count as independent.
- Different authors on the same forum may count as partially independent.
- Staff/mod response can raise authority.
- Cross-posts, scraped reposts, or obvious summaries of the same post should
  count once.

Conflicts:

- Equivalent claims with incompatible values create contested clusters.
- Contested clusters can still enter reports, but as uncertainty or risk rather
  than settled fact.

## Scoring

Do not assign high confidence purely from source type. Score both individual
sources and claim clusters.

### Source Confidence

Initial source confidence ranges:

- Official forum with staff or moderator response: `0.85 - 0.92`
- Official forum ordinary user thread: `0.65 - 0.78`
- GitHub issue or discussion with maintainer response: `0.82 - 0.90`
- GitHub issue or discussion with user-only discussion: `0.68 - 0.80`
- Reddit high-interaction thread: `0.55 - 0.72`
- G2/Capterra/TrustRadius review: `0.65 - 0.80`
- Developer blog or SEO blog: `0.45 - 0.65`
- Snippet-only source: capped at `0.55`

### Cluster Confidence

Cluster confidence can exceed any single weak source when independent sources
agree.

- One weak community source: capped at `0.55`
- Two independent community sources agree: up to `0.70`
- Three or more independent recent sources agree: `0.80 - 0.86`
- Staff/mod/maintainer support is present: `0.88 - 0.92`
- Official source and community cluster agree: `0.95+`

### Downranking

Downrank when:

- The source is older than 180 days for fast-changing fields.
- The claim is vague, speculative, or framed as a question.
- Sources are not independent.
- Only snippets are available.
- Conflicting evidence is equally strong.
- The source cannot be fetched and only a search result is available.

### Output Labels

Every clustered claim receives one label:

- `official_confirmed`
- `community_triangulated`
- `community_observed`
- `community_contested`
- `insufficient_evidence`

## Evidence Admission

Triangulated community claims may feed:

- comparison matrix caveats
- review summary
- user evaluation
- risk assessment
- pricing and limits caveats
- switching triggers
- risk-adjusted recommendation

Community claims must not become official facts unless official evidence also
supports them.

Required wording pattern:

> Multiple recent community sources consistently indicate X, but this is a
> high-confidence community observation rather than an official commitment.

## Writer Behavior

The writer should distinguish:

- Official fact: `Official docs state...`
- Triangulated community observation: `Multiple recent community sources
  consistently report...`
- Contested community observation: `Community evidence is split...`
- Evidence gap: `No sufficiently consistent public community evidence was
  found...`

Reports should add or strengthen these sections:

- User Review Summary
- Community Evidence Triangulation
- Actual-Use Risks
- Official Facts vs Community Observations
- Pricing and Limits Caveats

For Cursor pricing, the report should not stop at `unknown` if community
triangulation found consistent evidence. It should say that official collection
did not fully confirm the facts, then describe the community-triangulated
observation and its confidence.

## Winner Semantics

Mixed recommendation mode uses multiple winner concepts:

- `official_winner`: based on official or verified evidence.
- `community_adjusted_winner`: incorporates triangulated community claims.
- `risk_adjusted_recommendation`: combines official facts, community
  observations, conflicts, and gaps.

Community evidence may affect risk-adjusted recommendations and actual-use
judgments. It must not silently overwrite official facts.

## QA Behavior

QA should check:

- Was community triangulation attempted for each competitor and dimension?
- Were official gaps followed by targeted community searches?
- Does each high-confidence community claim have independent sources?
- Are source types classified correctly?
- Did writer present community observations as official commitments?
- Did writer ignore high-confidence community claims in user review, risks, or
  pricing caveats?
- Are contested claims labeled as contested?
- Are snippet-only claims prevented from high-confidence clusters?

Blockers:

- Community observation written as official commitment.
- High-impact claim has no source cluster or only snippet-only support.
- Official and community evidence conflict but report hides the conflict.

Warnings:

- Community search had no useful results.
- Claim cluster has only one community source.
- Community evidence is old for a fast-changing dimension.
- High-confidence community cluster is absent from the report body.

## Error Handling

If a source cannot be fetched:

- Keep search result as `snippet_only`.
- Cap confidence at `0.55`.
- Do not use it in high-confidence clusters unless supported by fetched sources.

If robots, login, or anti-bot blocks access:

- Record the access issue in metadata.
- Use the source only as low-confidence context.

If evidence conflicts:

- Create `community_contested`.
- Show both sides with dates and source types.
- Do not produce a settled community claim.

If a thread is a question rather than confirmation:

- Treat it as a signal of confusion or pain, not as a factual claim.

## Testing

Required tests:

- Query planner generates community queries for pricing, feature, persona, and
  review dimensions.
- Source classifier labels Reddit, GitHub Discussions, GitHub Issues, Cursor
  forum, G2, Capterra, and developer blogs correctly.
- Claim extractor pulls concrete pricing, limits, complaint, feature
  limitation, and switching-trigger claims.
- Cluster scorer raises confidence for independent agreement and lowers
  confidence for old, snippet-only, non-independent, or contested evidence.
- QA warns when community triangulation is skipped for official gaps.
- QA blocks when community observations are written as official commitments.
- Writer renders official facts separately from community observations.
- Regression fixture based on run `run-819bc12ba6bf7eb220944ddf1d8db06c`
  verifies that Cursor pricing and community/forum evidence can enter report
  caveats instead of leaving the report at `unknown`.

## Success Criteria

New runs should satisfy:

- Each competitor has community evidence or explicit no-result metadata.
- User Review Summary no longer relies primarily on simulated surveys.
- Official gaps such as Cursor pricing produce official-gap plus community
  triangulation output.
- Community high-confidence claims can affect actual-use and risk judgments.
- Community claims do not masquerade as official commitments.
- Release gate distinguishes weak community evidence from incorrectly used
  community evidence.

## Out of Scope

- Login-only scraping.
- Private Slack/Discord communities.
- Browser automation for sites that block normal fetching.
- Treating Reddit or forum posts as official commitments without official
  support.
- Full UI redesign for evidence browsing.
