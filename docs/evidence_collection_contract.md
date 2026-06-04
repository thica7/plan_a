# Evidence Collection Contract

This contract keeps competitor identity, official source selection, and web evidence fetching
consistent across planner, collector, skill tools, and report projection.

## Competitor Identity

Module: `backend/packages/business_intel/entity_resolver.py`

Public entry points:

- `resolve_competitor_identity(competitor) -> CompetitorIdentity | None`
- `trusted_source_candidates(competitor, dimension) -> list[TrustedSourceCandidate]`
- `is_trusted_url_for_competitor(competitor, url) -> bool`
- `identity_terms_for_competitor(competitor) -> tuple[str, ...]`
- `confusion_terms_for_competitor(competitor) -> tuple[str, ...]`
- `search_qualifier_for_competitor(competitor) -> str`

Rules:

- Unknown competitors are not promoted to verified identities.
- Short or ambiguous names do not fuzzy-match known identities unless the normalized key is
  long enough to be safe.
- Trusted domains improve ranking and confidence, but fetched content still must pass collector
  quality checks before becoming `RawSource`.

## Official Source Candidates

Module: `backend/packages/tools/official_docs.py`

`find_official_docs(competitor, dimension, homepage_hint)` returns:

1. Resolver-backed trusted source seeds for known entities.
2. Homepage-derived generic paths only when a verified homepage hint exists.
3. Deduplicated URLs in stable priority order.

Collector, ReAct skill tools, and official-first collection all use this same function.

## Evidence Fetching

Module: `backend/packages/tools/evidence_fetch.py`

`fetch_evidence_page(url)` returns `EvidenceFetchResult`, compatible with the old
`FetchPageResult` fields and extended with:

- `fetch_method`: `basic_httpx`, `basic_httpx_low_quality`, or `webfetch_v2:<method>`
- `quality_score`
- `text_length`
- `failure_reason`

Flow:

1. Try fast `fetch_page`.
2. If the text is weak or the fetch fails, call `webfetch_v2` through `advanced_fetch_page`.
3. If both fail, return structured failure data instead of creating evidence.

Collector rule:

- Real runs require verified fetched web evidence for planned dimensions.
- Search results are candidates, not evidence, until fetch succeeds.
- Failed candidates are traced as `source_candidate_rejected` with a failure reason.
