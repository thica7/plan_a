# Community Triangulation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class community evidence lane so Reddit, forums, GitHub discussions/issues, review sites, and developer posts can be collected, triangulated, safely scored, and used in reports without masquerading as official facts.

**Architecture:** Keep official collection as the source of official commitments, and add a separate community lane with its own query planning, source classification, claim extraction, cluster scoring, collector integration, QA checks, and writer context. Store results in existing `RawSource.metadata` and `source_type` fields to avoid a schema migration, then let analyst, comparator, and writer consume the enriched sources through existing source IDs.

**Tech Stack:** Python 3.12, Pydantic DTOs, pytest, ruff, existing collector/research/analyst/writer mixins, existing conda environment at `D:\Anaconda\envs\bd-competiscope-v2\python.exe`.

---

## File Structure

- Create `backend/packages/community/__init__.py`
  - Exports the community planner, classifier, claim extractor, cluster scorer, and RawSource helpers.

- Create `backend/packages/community/models.py`
  - Owns typed community source classifications, claims, and claim clusters.

- Create `backend/packages/community/query_planner.py`
  - Builds bounded community search queries for pricing, feature, persona, review, adoption, and generic dimensions.

- Create `backend/packages/community/source_classifier.py`
  - Classifies URL/title/snippet combinations into `reddit_thread`, `github_discussion`, `github_issue`, `community_forum`, `review_site`, `developer_blog`, or `snippet_only`.

- Create `backend/packages/community/claims.py`
  - Extracts concrete community claims from `RawSource` snippets and clusters equivalent claims by competitor, dimension, kind, and normalized value.

- Create `backend/packages/community/scoring.py`
  - Scores source confidence and cluster confidence with independence, staff/mod/maintainer signals, snippet-only caps, conflict rules, and recency hints when metadata is available.

- Create `backend/packages/community/raw_sources.py`
  - Reclassifies fetched community `RawSource` objects and creates capped `snippet_only` sources when fetching fails but the search snippet is useful.

- Modify `backend/packages/research/models.py`
  - Add `community_search` to `CandidateOrigin`.

- Modify `backend/packages/research/discovery/constants.py`
  - Add a source origin priority for `community_search`.

- Modify `backend/packages/research/discovery/providers.py`
  - Accept `community_search` in `_candidate_origin`.

- Modify `backend/packages/research/capture/policy.py`
  - Keep low-confidence community candidates deferrable below `0.45` while allowing useful community candidates through.

- Modify `backend/packages/config/settings.py`
  - Add bounded community collector settings with environment overrides.

- Modify `backend/packages/schema/messages.py`
  - Register the `CommunitySearchSummary` agent-message payload used to audit attempted community searches and no-result outcomes.

- Modify `backend/packages/agents/collectors/logic.py`
  - Run the community lane for every competitor/dimension after the normal branch collection.
  - Trace query counts, candidate counts, fetched community sources, snippet-only fallbacks, and claim cluster metadata.
  - Annotate community clusters in `collect_join`.

- Modify `backend/packages/agents/collectors/skill_tools.py`
  - Make `search_review_site` execute the same deterministic community query path when a skill uses that tool.

- Modify `backend/packages/agents/analysts/logic.py`
  - Enrich `review_summary` and persona/adoption claims from community clusters when source IDs are present.

- Modify `backend/packages/agents/comparator/logic.py`
  - Keep community sources out of official winner voting while adding explicit community-adjusted matrix caveats.

- Modify `backend/packages/agents/writer/logic.py`
  - Expose community source metadata and claim clusters in the writer context.
  - Add required report wording for official facts versus community observations.

- Modify `backend/packages/i18n/language.py`
  - Add the localized `community_evidence_triangulation` report label used by writer and report-quality checks.

- Modify `backend/packages/agents/qa/logic.py`
  - Treat community source types as public persona/review signals.
  - Warn when community triangulation is skipped for official gaps.
  - Block high-impact report text that states community observations as official commitments.

- Modify `backend/packages/business_intel/report_quality.py`
  - Treat community source types as real/public source signals and review-theme sources.
  - Add community sections to quality expectations when community evidence exists.

- Add `backend/tests/unit/test_community_query_planner.py`
  - Focused tests for query generation.

- Add `backend/tests/unit/test_community_source_classifier.py`
  - Focused tests for source type classification and base confidence.

- Add `backend/tests/unit/test_community_claims.py`
  - Focused tests for concrete claim extraction, clustering, scoring, and conflict labeling.

- Modify `backend/tests/unit/test_run_service.py`
  - Service-level collector, analyst, QA, and writer regression tests.

- Modify `backend/tests/unit/test_report_quality.py`
  - Quality tests for community-backed user review and official/community separation.

---

### Task 1: Community Query Planner

**Files:**
- Create: `backend/packages/community/__init__.py`
- Create: `backend/packages/community/models.py`
- Create: `backend/packages/community/query_planner.py`
- Add: `backend/tests/unit/test_community_query_planner.py`

- [ ] **Step 1: Add failing query planner tests**

Create `backend/tests/unit/test_community_query_planner.py` with:

```python
from __future__ import annotations

from packages.community.query_planner import build_community_queries


def test_pricing_queries_include_forum_reddit_and_github_discussion() -> None:
    queries = build_community_queries(
        competitor="Cursor",
        dimension="pricing",
        topic="AI coding assistants",
        limit=4,
    )

    assert queries == [
        "Cursor pricing usage limit reddit AI coding assistants",
        "Cursor pricing usage limit forum AI coding assistants",
        "Cursor billing quota GitHub discussion AI coding assistants",
        "Cursor hidden limit cost overage AI coding assistants",
    ]


def test_feature_queries_include_issue_and_limitation_language() -> None:
    queries = build_community_queries(
        competitor="GitHub Copilot",
        dimension="feature",
        topic="AI coding assistants",
        limit=3,
    )

    assert queries == [
        "GitHub Copilot context window issue discussion AI coding assistants",
        "GitHub Copilot agent mode complaints reddit AI coding assistants",
        "GitHub Copilot feature limitation forum AI coding assistants",
    ]


def test_persona_queries_include_adoption_and_switching_language() -> None:
    queries = build_community_queries(
        competitor="Claude Code",
        dimension="persona",
        topic="AI coding assistants",
        limit=3,
    )

    assert queries == [
        "Claude Code user reviews pros cons reddit AI coding assistants",
        "Claude Code switched from Claude Code to alternative AI coding assistants",
        "Claude Code adoption blockers enterprise developers AI coding assistants",
    ]


def test_review_queries_prioritize_public_review_sites() -> None:
    queries = build_community_queries(
        competitor="Windsurf",
        dimension="review",
        topic="AI coding assistants",
        limit=4,
    )

    assert queries == [
        "Windsurf G2 reviews pros cons AI coding assistants",
        "Windsurf Capterra reviews AI coding assistants",
        "Windsurf TrustRadius reviews AI coding assistants",
        "Windsurf customer complaints alternatives AI coding assistants",
    ]


def test_query_planner_dedupes_and_respects_limit() -> None:
    queries = build_community_queries(
        competitor="Cursor",
        dimension="pricing and review",
        topic="AI coding assistants",
        limit=3,
    )

    assert len(queries) == 3
    assert len(set(queries)) == 3
    assert all("  " not in query for query in queries)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_community_query_planner.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'packages.community'`.

- [ ] **Step 3: Add community models used by later tasks**

Create `backend/packages/community/models.py` with:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CommunitySourceType = Literal[
    "community_forum",
    "reddit_thread",
    "github_discussion",
    "github_issue",
    "review_site",
    "developer_blog",
    "snippet_only",
]

CommunityClaimKind = Literal[
    "pricing",
    "usage_limit",
    "feature_limitation",
    "praise",
    "complaint",
    "adoption_blocker",
    "switching_trigger",
    "persona_signal",
]

CommunityClusterLabel = Literal[
    "official_confirmed",
    "community_triangulated",
    "community_observed",
    "community_contested",
    "insufficient_evidence",
]


class CommunitySourceClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: CommunitySourceType
    is_community: bool
    base_confidence: float = Field(ge=0.0, le=1.0)
    authority_signal: str = "user"
    reason: str = ""


class CommunityClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str
    dimension: str
    kind: CommunityClaimKind
    claim: str
    normalized_value: str = ""
    source_id: str
    source_type: CommunitySourceType
    url: str = ""
    evidence: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    recency_hint: str = ""
    author_signal: str = "user"
    is_snippet_only: bool = False
    uncertainty: str = ""


class CommunityClaimCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str
    dimension: str
    kind: CommunityClaimKind
    normalized_value: str = ""
    label: CommunityClusterLabel
    claim: str
    source_ids: list[str] = Field(default_factory=list)
    source_types: list[CommunitySourceType] = Field(default_factory=list)
    independent_domain_count: int = 0
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    conflict_values: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Add package exports**

Create `backend/packages/community/__init__.py` with:

```python
from packages.community.models import (
    CommunityClaim,
    CommunityClaimCluster,
    CommunitySourceClassification,
)
from packages.community.query_planner import build_community_queries

__all__ = [
    "CommunityClaim",
    "CommunityClaimCluster",
    "CommunitySourceClassification",
    "build_community_queries",
]
```

- [ ] **Step 5: Implement the query planner**

Create `backend/packages/community/query_planner.py` with:

```python
from __future__ import annotations


def build_community_queries(
    *,
    competitor: str,
    dimension: str,
    topic: str,
    limit: int = 3,
) -> list[str]:
    normalized_dimension = dimension.casefold().replace("-", "_")
    if "pricing" in normalized_dimension or "billing" in normalized_dimension:
        intents = [
            "pricing usage limit reddit",
            "pricing usage limit forum",
            "billing quota GitHub discussion",
            "hidden limit cost overage",
        ]
    elif "review" in normalized_dimension or "feedback" in normalized_dimension:
        intents = [
            "G2 reviews pros cons",
            "Capterra reviews",
            "TrustRadius reviews",
            "customer complaints alternatives",
        ]
    elif any(
        token in normalized_dimension
        for token in ("persona", "user", "customer", "buyer", "adoption", "switching")
    ):
        intents = [
            "user reviews pros cons reddit",
            f"switched from {competitor} to alternative",
            "adoption blockers enterprise developers",
            "onboarding workflow fit complaint",
        ]
    elif "feature" in normalized_dimension or "capability" in normalized_dimension:
        intents = [
            "context window issue discussion",
            "agent mode complaints reddit",
            "feature limitation forum",
            "bug issue developer workflow",
        ]
    else:
        intents = [
            "reddit user complaints",
            "forum limitations",
            "GitHub issue discussion",
            "developer review pros cons",
        ]
    return _dedupe(
        f"{competitor} {intent} {topic}".strip()
        for intent in intents
    )[: max(0, limit)]


def _dedupe(queries: object) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in queries:
        query = " ".join(str(item).split()).strip()
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        result.append(query)
    return result
```

- [ ] **Step 6: Run the focused query planner tests and verify they pass**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_community_query_planner.py -q
```

Expected: PASS.

- [ ] **Step 7: Run ruff for the new files**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\community backend\tests\unit\test_community_query_planner.py
```

Expected: `All checks passed!`

- [ ] **Step 8: Commit Task 1**

Run:

```powershell
git add backend/packages/community backend/tests/unit/test_community_query_planner.py
git commit -m "feat: add community query planner"
```

---

### Task 2: Community Source Classification

**Files:**
- Create: `backend/packages/community/source_classifier.py`
- Modify: `backend/packages/research/models.py`
- Modify: `backend/packages/research/discovery/constants.py`
- Modify: `backend/packages/research/discovery/providers.py`
- Modify: `backend/packages/research/capture/policy.py`
- Add: `backend/tests/unit/test_community_source_classifier.py`

- [ ] **Step 1: Add failing source classifier tests**

Create `backend/tests/unit/test_community_source_classifier.py` with:

```python
from __future__ import annotations

from packages.community.source_classifier import classify_community_source
from packages.research.models import SourceCandidate


def test_classifies_reddit_thread() -> None:
    result = classify_community_source(
        url="https://www.reddit.com/r/cursor/comments/abc123/cursor_pricing_limits/",
        title="Cursor pricing limits?",
        snippet="Users report Cursor Pro usage limits and cost confusion.",
    )

    assert result.source_type == "reddit_thread"
    assert result.is_community is True
    assert result.base_confidence == 0.62


def test_classifies_github_discussion_and_issue() -> None:
    discussion = classify_community_source(
        url="https://github.com/org/repo/discussions/42",
        title="Copilot billing discussion",
        snippet="Maintainer answered the billing quota question.",
    )
    issue = classify_community_source(
        url="https://github.com/org/repo/issues/99",
        title="Context window limitation",
        snippet="Maintainer confirmed the issue is a known limitation.",
    )

    assert discussion.source_type == "github_discussion"
    assert discussion.authority_signal == "maintainer"
    assert discussion.base_confidence == 0.86
    assert issue.source_type == "github_issue"
    assert issue.authority_signal == "maintainer"


def test_classifies_official_forum_and_review_site() -> None:
    forum = classify_community_source(
        url="https://forum.cursor.com/t/usage-based-pricing/123",
        title="Usage based pricing",
        snippet="A staff member explains current usage limits.",
    )
    review = classify_community_source(
        url="https://www.g2.com/products/cursor/reviews",
        title="Cursor reviews",
        snippet="Users list pros, cons, and adoption blockers.",
    )

    assert forum.source_type == "community_forum"
    assert forum.authority_signal == "staff"
    assert forum.base_confidence == 0.88
    assert review.source_type == "review_site"
    assert review.base_confidence == 0.72


def test_classifies_developer_blog_and_non_community() -> None:
    blog = classify_community_source(
        url="https://dev.to/team/cursor-vs-copilot-review",
        title="Cursor vs Copilot hands-on review",
        snippet="A developer compares limitations and workflow fit.",
    )
    official = classify_community_source(
        url="https://docs.github.com/en/copilot",
        title="GitHub Copilot docs",
        snippet="Official product documentation.",
    )

    assert blog.source_type == "developer_blog"
    assert blog.base_confidence == 0.56
    assert official.is_community is False
    assert official.reason == "not_community_source"


def test_community_search_candidate_origin_is_accepted() -> None:
    candidate = SourceCandidate(
        title="Cursor pricing reddit",
        url="https://reddit.com/r/cursor/comments/abc",
        snippet="Cursor Pro is reported at $20 per month.",
        origin="community_search",
        competitor="Cursor",
        dimension="pricing",
    )

    assert candidate.origin == "community_search"
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_community_source_classifier.py -q
```

Expected: FAIL because `source_classifier.py` does not exist and `community_search` is not an accepted `CandidateOrigin`.

- [ ] **Step 3: Implement the source classifier**

Create `backend/packages/community/source_classifier.py` with:

```python
from __future__ import annotations

from urllib.parse import urlparse

from packages.community.models import CommunitySourceClassification


def classify_community_source(
    *,
    url: str,
    title: str = "",
    snippet: str = "",
) -> CommunitySourceClassification:
    host = (urlparse(url).hostname or "").casefold().removeprefix("www.")
    path = urlparse(url).path.casefold()
    text = f"{title} {snippet}".casefold()
    authority = _authority_signal(text)

    if host.endswith("reddit.com"):
        return CommunitySourceClassification(
            source_type="reddit_thread",
            is_community=True,
            base_confidence=0.62,
            authority_signal=authority,
            reason="reddit_thread",
        )
    if host == "github.com" and "/discussions/" in path:
        return CommunitySourceClassification(
            source_type="github_discussion",
            is_community=True,
            base_confidence=0.86 if authority == "maintainer" else 0.74,
            authority_signal=authority,
            reason="github_discussion",
        )
    if host == "github.com" and "/issues/" in path:
        return CommunitySourceClassification(
            source_type="github_issue",
            is_community=True,
            base_confidence=0.86 if authority == "maintainer" else 0.74,
            authority_signal=authority,
            reason="github_issue",
        )
    if _is_review_site(host):
        return CommunitySourceClassification(
            source_type="review_site",
            is_community=True,
            base_confidence=0.72,
            authority_signal=authority,
            reason="review_site",
        )
    if _is_forum(host, path):
        return CommunitySourceClassification(
            source_type="community_forum",
            is_community=True,
            base_confidence=0.88 if authority == "staff" else 0.70,
            authority_signal=authority,
            reason="community_forum",
        )
    if _is_developer_blog(host):
        return CommunitySourceClassification(
            source_type="developer_blog",
            is_community=True,
            base_confidence=0.56,
            authority_signal=authority,
            reason="developer_blog",
        )
    return CommunitySourceClassification(
        source_type="snippet_only",
        is_community=False,
        base_confidence=0.35,
        authority_signal=authority,
        reason="not_community_source",
    )


def _authority_signal(text: str) -> str:
    if any(token in text for token in ("maintainer", "owner", "member")):
        return "maintainer"
    if any(token in text for token in ("staff", "moderator", "mod response", "admin")):
        return "staff"
    return "user"


def _is_review_site(host: str) -> bool:
    return any(
        host.endswith(domain)
        for domain in ("g2.com", "capterra.com", "trustradius.com", "producthunt.com")
    )


def _is_forum(host: str, path: str) -> bool:
    return (
        host.startswith("forum.")
        or host.startswith("community.")
        or "discourse" in host
        or "/forum/" in path
        or "/t/" in path
    )


def _is_developer_blog(host: str) -> bool:
    return any(
        host.endswith(domain)
        for domain in ("dev.to", "medium.com", "substack.com", "hashnode.dev")
    )
```

- [ ] **Step 4: Export the source classifier from the package**

Update `backend/packages/community/__init__.py` to add:

```python
from packages.community.source_classifier import classify_community_source
```

Add this string to `__all__`:

```python
    "classify_community_source",
```

- [ ] **Step 5: Add `community_search` candidate origin**

In `backend/packages/research/models.py`, update `CandidateOrigin` to include `community_search`:

```python
CandidateOrigin = Literal[
    "trusted_registry",
    "perplexity",
    "web_search",
    "community_search",
    "homepage_derived",
    "llm_fallback",
    "manual",
]
```

- [ ] **Step 6: Rank community search below general web search but above homepage fallback**

In `backend/packages/research/discovery/constants.py`, update `SOURCE_ORIGIN_PRIORITY` to:

```python
SOURCE_ORIGIN_PRIORITY: dict[str, int] = {
    "trusted_registry": 400,
    "perplexity": 300,
    "web_search": 280,
    "community_search": 260,
    "homepage_derived": 120,
    "llm_fallback": 40,
}
```

- [ ] **Step 7: Accept the new origin in provider normalization**

In `backend/packages/research/discovery/providers.py`, add `"community_search"` to the `_candidate_origin()` allowed set:

```python
    if normalized in {
        "trusted_registry",
        "perplexity",
        "web_search",
        "community_search",
        "homepage_derived",
        "llm_fallback",
        "manual",
    }:
```

- [ ] **Step 8: Keep very weak community candidates as fallback**

In `backend/packages/research/capture/policy.py`, add this branch to `fallback_candidate_reason()` after the homepage branch:

```python
    if candidate.origin == "community_search" and candidate.confidence < 0.45:
        return "deferred_low_confidence_community_search"
```

- [ ] **Step 9: Run source classifier tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_community_source_classifier.py -q
```

Expected: PASS.

- [ ] **Step 10: Run ruff for touched files**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\community backend\packages\research\models.py backend\packages\research\discovery\constants.py backend\packages\research\discovery\providers.py backend\packages\research\capture\policy.py backend\tests\unit\test_community_source_classifier.py
```

Expected: `All checks passed!`

- [ ] **Step 11: Commit Task 2**

Run:

```powershell
git add backend/packages/community/__init__.py backend/packages/community/source_classifier.py backend/packages/research/models.py backend/packages/research/discovery/constants.py backend/packages/research/discovery/providers.py backend/packages/research/capture/policy.py backend/tests/unit/test_community_source_classifier.py
git commit -m "feat: classify community sources"
```

---

### Task 3: Community Claim Extraction And Cluster Scoring

**Files:**
- Create: `backend/packages/community/claims.py`
- Create: `backend/packages/community/scoring.py`
- Add: `backend/tests/unit/test_community_claims.py`

- [ ] **Step 1: Add failing tests for extraction, clustering, and scoring**

Create `backend/tests/unit/test_community_claims.py` with:

```python
from __future__ import annotations

from packages.community.claims import (
    cluster_community_claims,
    extract_community_claims_from_source,
)
from packages.schema.models import RawSource


def test_extracts_concrete_pricing_and_limit_claims() -> None:
    source = _source(
        source_id="reddit-cursor-pricing",
        source_type="reddit_thread",
        snippet=(
            "Users report Cursor Pro is $20 per month and Ultra is $200 per month. "
            "Several comments mention usage limits and quota confusion."
        ),
    )

    claims = extract_community_claims_from_source(source)

    assert [claim.kind for claim in claims] == ["pricing", "pricing", "usage_limit"]
    assert claims[0].normalized_value == "$20 per month"
    assert claims[1].normalized_value == "$200 per month"
    assert claims[2].normalized_value == "usage limits"


def test_extracts_complaints_switching_and_feature_limitation() -> None:
    source = _source(
        source_id="github-feature-limit",
        source_type="github_issue",
        dimension="feature",
        snippet=(
            "Users complain about context window limitations in large repositories. "
            "One team switched from Cursor to Copilot because enterprise rollout was easier."
        ),
    )

    claims = extract_community_claims_from_source(source)

    kinds = {claim.kind for claim in claims}
    assert "feature_limitation" in kinds
    assert "complaint" in kinds
    assert "switching_trigger" in kinds


def test_cluster_confidence_rises_with_independent_agreement() -> None:
    sources = [
        _source("reddit-cursor-pricing", "reddit_thread", "Cursor Pro is $20 per month."),
        _source("forum-cursor-pricing", "community_forum", "Cursor Pro price is $20 per month."),
        _source("g2-cursor-pricing", "review_site", "Cursor Pro costs $20 per month."),
    ]
    claims = [
        claim
        for source in sources
        for claim in extract_community_claims_from_source(source)
    ]

    clusters = cluster_community_claims(claims)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.label == "community_triangulated"
    assert cluster.confidence >= 0.80
    assert cluster.independent_domain_count == 3
    assert cluster.source_ids == [
        "reddit-cursor-pricing",
        "forum-cursor-pricing",
        "g2-cursor-pricing",
    ]


def test_cluster_keeps_distinct_pricing_values_separate() -> None:
    sources = [
        _source("reddit-cursor-20", "reddit_thread", "Cursor Pro is $20 per month."),
        _source("forum-cursor-25", "community_forum", "Cursor Pro is $25 per month."),
    ]
    claims = [
        claim
        for source in sources
        for claim in extract_community_claims_from_source(source)
    ]

    clusters = cluster_community_claims(claims)

    assert [cluster.normalized_value for cluster in clusters] == [
        "$20 per month",
        "$25 per month",
    ]
    assert all(cluster.label == "community_observed" for cluster in clusters)
    assert all(cluster.conflict_values == [] for cluster in clusters)


def test_single_snippet_only_source_is_capped() -> None:
    source = _source(
        source_id="snippet-only",
        source_type="snippet_only",
        snippet="Search result says Cursor Pro is $20 per month.",
    )

    claims = extract_community_claims_from_source(source)
    clusters = cluster_community_claims(claims)

    assert clusters[0].label == "community_observed"
    assert clusters[0].confidence == 0.55


def _source(
    source_id: str,
    source_type: str,
    snippet: str,
    *,
    dimension: str = "pricing",
) -> RawSource:
    return RawSource(
        id=source_id,
        competitor="Cursor",
        dimension=dimension,
        source_type=source_type,
        title=source_id,
        url=f"https://example-{source_id}.com/thread",
        snippet=snippet,
        content_hash=f"{source_id}-hash",
        confidence=0.72 if source_type != "snippet_only" else 0.55,
        metadata={
            "community_evidence": True,
            "community_source_type": source_type,
        },
    )
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_community_claims.py -q
```

Expected: FAIL because `claims.py` and `scoring.py` do not exist.

- [ ] **Step 3: Implement cluster scoring**

Create `backend/packages/community/scoring.py` with:

```python
from __future__ import annotations

from urllib.parse import urlparse

from packages.community.models import CommunityClaim


def independent_domain_count(claims: list[CommunityClaim]) -> int:
    domains = {_domain(claim.url) for claim in claims if _domain(claim.url)}
    return len(domains)


def cluster_confidence(claims: list[CommunityClaim], *, contested: bool) -> float:
    if not claims:
        return 0.0
    if all(claim.is_snippet_only for claim in claims):
        return 0.55
    source_count = len({claim.source_id for claim in claims})
    domain_count = independent_domain_count(claims)
    has_staff_signal = any(
        claim.author_signal in {"staff", "maintainer"} for claim in claims
    )
    if contested:
        return min(0.72, max(claim.confidence for claim in claims) - 0.08)
    if has_staff_signal and source_count >= 1:
        return min(0.92, max(claim.confidence for claim in claims) + 0.06)
    if domain_count >= 3:
        return 0.82
    if domain_count >= 2:
        return 0.70
    return min(0.65, max(claim.confidence for claim in claims))


def _domain(url: str) -> str:
    return (urlparse(url).hostname or "").casefold().removeprefix("www.")
```

- [ ] **Step 4: Implement claim extraction and clustering**

Create `backend/packages/community/claims.py` with:

```python
from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlparse

from packages.community.models import CommunityClaim, CommunityClaimCluster
from packages.community.scoring import cluster_confidence, independent_domain_count
from packages.schema.models import RawSource

COMMUNITY_SOURCE_TYPES = {
    "community_forum",
    "reddit_thread",
    "github_discussion",
    "github_issue",
    "review_site",
    "developer_blog",
    "snippet_only",
}


def extract_community_claims_from_source(source: RawSource) -> list[CommunityClaim]:
    if source.source_type not in COMMUNITY_SOURCE_TYPES and not source.metadata.get(
        "community_evidence"
    ):
        return []
    text = " ".join([source.title, source.snippet]).strip()
    claims: list[CommunityClaim] = []
    claims.extend(_pricing_claims(source, text))
    claims.extend(_usage_limit_claims(source, text))
    claims.extend(_feature_claims(source, text))
    claims.extend(_review_claims(source, text))
    return _dedupe_claims(claims)


def cluster_community_claims(claims: list[CommunityClaim]) -> list[CommunityClaimCluster]:
    grouped: dict[tuple[str, str, str, str], list[CommunityClaim]] = defaultdict(list)
    for claim in claims:
        grouped[_cluster_key(claim)].append(claim)

    clusters: list[CommunityClaimCluster] = []
    for (competitor, dimension, kind, key_value), items in grouped.items():
        values = sorted({item.normalized_value for item in items if item.normalized_value})
        contested = len(values) > 1 and not key_value
        if contested:
            cluster_items = items
            normalized_value = ""
        else:
            normalized_value = values[0] if values else ""
            cluster_items = items
        confidence = cluster_confidence(cluster_items, contested=contested)
        if contested:
            label = "community_contested"
        elif confidence >= 0.80:
            label = "community_triangulated"
        elif cluster_items:
            label = "community_observed"
        else:
            label = "insufficient_evidence"
        source_ids = _ordered_unique(item.source_id for item in cluster_items)
        source_types = _ordered_unique(item.source_type for item in cluster_items)
        evidence = _ordered_unique(item.evidence for item in cluster_items if item.evidence)
        clusters.append(
            CommunityClaimCluster(
                competitor=competitor,
                dimension=dimension,
                kind=kind,
                normalized_value=normalized_value,
                label=label,
                claim=_cluster_claim_text(kind, normalized_value, label),
                source_ids=source_ids,
                source_types=source_types,
                independent_domain_count=independent_domain_count(cluster_items),
                confidence=confidence,
                conflict_values=values if contested else [],
                evidence=evidence[:5],
            )
        )
    return sorted(
        clusters,
        key=lambda item: (item.competitor, item.dimension, item.kind, item.normalized_value),
    )


def _cluster_key(claim: CommunityClaim) -> tuple[str, str, str, str]:
    key_value = ""
    if claim.kind in {"pricing", "usage_limit"} and claim.normalized_value:
        key_value = claim.normalized_value
    return (claim.competitor, claim.dimension, claim.kind, key_value)


def _pricing_claims(source: RawSource, text: str) -> list[CommunityClaim]:
    claims: list[CommunityClaim] = []
    for match in re.finditer(
        r"\$\s?\d+(?:\.\d+)?\s*(?:/|per)\s*(?:month|mo|year|yr|user|seat|1m tokens|mtok|tokens?)",
        text,
        flags=re.IGNORECASE,
    ):
        value = _normalize_price(match.group(0))
        claims.append(_claim(source, "pricing", value, f"{source.competitor} is reported as {value}.", text))
    return claims


def _usage_limit_claims(source: RawSource, text: str) -> list[CommunityClaim]:
    normalized = text.casefold()
    if not any(token in normalized for token in ("usage limit", "quota", "rate limit", "credit limit")):
        return []
    value = "usage limits" if "limit" in normalized else "quota"
    return [_claim(source, "usage_limit", value, f"Users report {value}.", text)]


def _feature_claims(source: RawSource, text: str) -> list[CommunityClaim]:
    normalized = text.casefold()
    claims: list[CommunityClaim] = []
    if any(token in normalized for token in ("context window", "limitation", "bug", "issue")):
        claims.append(_claim(source, "feature_limitation", "feature limitation", "Users report feature limitations.", text))
    return claims


def _review_claims(source: RawSource, text: str) -> list[CommunityClaim]:
    normalized = text.casefold()
    claims: list[CommunityClaim] = []
    if any(token in normalized for token in ("complain", "complaint", "confusing", "friction", "pain")):
        claims.append(_claim(source, "complaint", "complaint", "Users report complaints or friction.", text))
    if any(token in normalized for token in ("adoption blocker", "rollout", "procurement", "security review", "onboarding")):
        claims.append(_claim(source, "adoption_blocker", "adoption blocker", "Users report adoption blockers.", text))
    if "switched from" in normalized or "switching" in normalized:
        claims.append(_claim(source, "switching_trigger", "switching trigger", "Users report switching triggers.", text))
    if any(token in normalized for token in ("developer", "team", "enterprise", "buyer")):
        claims.append(_claim(source, "persona_signal", "persona signal", "Community source describes user or buyer segments.", text))
    return claims


def _claim(
    source: RawSource,
    kind: str,
    normalized_value: str,
    claim_text: str,
    text: str,
) -> CommunityClaim:
    source_type = str(source.metadata.get("community_source_type") or source.source_type)
    return CommunityClaim(
        competitor=source.competitor,
        dimension=source.dimension,
        kind=kind,
        claim=claim_text,
        normalized_value=normalized_value,
        source_id=source.id,
        source_type=source_type,
        url=str(source.url or ""),
        evidence=_evidence_window(text, normalized_value),
        confidence=source.confidence,
        author_signal=str(source.metadata.get("community_authority_signal") or "user"),
        is_snippet_only=source.source_type == "snippet_only",
    )


def _normalize_price(value: str) -> str:
    normalized = " ".join(value.replace("/", " per ").split())
    normalized = normalized.replace(" mo", " month").replace(" yr", " year")
    return normalized


def _evidence_window(text: str, needle: str) -> str:
    if not needle:
        return " ".join(text.split())[:220]
    normalized = text.casefold()
    index = normalized.find(needle.casefold())
    if index < 0:
        return " ".join(text.split())[:220]
    start = max(0, index - 90)
    end = min(len(text), index + len(needle) + 130)
    return " ".join(text[start:end].split())[:240]


def _cluster_claim_text(kind: str, normalized_value: str, label: str) -> str:
    if kind == "pricing" and normalized_value:
        return f"Multiple community sources report pricing at {normalized_value}."
    if kind == "usage_limit":
        return "Community sources report usage limit or quota concerns."
    if kind == "feature_limitation":
        return "Community sources report feature limitations in actual use."
    if kind == "switching_trigger":
        return "Community sources describe switching triggers."
    if label == "community_contested":
        return "Community sources conflict on this claim."
    return "Community sources describe user sentiment or adoption signals."


def _dedupe_claims(claims: list[CommunityClaim]) -> list[CommunityClaim]:
    result: list[CommunityClaim] = []
    seen: set[tuple[str, str, str]] = set()
    for claim in claims:
        key = (claim.kind, claim.normalized_value, claim.source_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(claim)
    return result


def _ordered_unique(values: object) -> list:
    result = []
    seen = set()
    for value in values:
        key = str(value).casefold()
        if not str(value).strip() or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
```

- [ ] **Step 5: Export claim helpers from the package**

Update `backend/packages/community/__init__.py` to add:

```python
from packages.community.claims import (
    cluster_community_claims,
    extract_community_claims_from_source,
)
```

Add these strings to `__all__`:

```python
    "cluster_community_claims",
    "extract_community_claims_from_source",
```

- [ ] **Step 6: Run the focused claim tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_community_claims.py -q
```

Expected: PASS.

- [ ] **Step 7: Run ruff for touched files**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\community backend\tests\unit\test_community_claims.py
```

Expected: `All checks passed!`

- [ ] **Step 8: Commit Task 3**

Run:

```powershell
git add backend/packages/community/claims.py backend/packages/community/scoring.py backend/tests/unit/test_community_claims.py backend/packages/community/__init__.py
git commit -m "feat: triangulate community claims"
```

---

### Task 4: RawSource Helpers For Community Evidence

**Files:**
- Create: `backend/packages/community/raw_sources.py`
- Add tests in: `backend/tests/unit/test_community_source_classifier.py`

- [ ] **Step 1: Add failing RawSource helper tests**

Append to `backend/tests/unit/test_community_source_classifier.py`:

```python
from packages.community.raw_sources import (
    reclassify_community_source,
    snippet_only_source_from_candidate,
)
from packages.research.models import SourceCandidate
from packages.schema.models import RawSource


def test_reclassify_community_source_updates_type_id_and_metadata() -> None:
    source = RawSource(
        id="old-webpage-id",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor forum pricing",
        url="https://forum.cursor.com/t/pricing-limits/1",
        snippet="A staff member says users should check current usage limits.",
        content_hash="hash",
        confidence=0.76,
    )

    updated = reclassify_community_source(source, run_id="run-1")

    assert updated.id != source.id
    assert updated.source_type == "community_forum"
    assert updated.metadata["community_evidence"] is True
    assert updated.metadata["community_source_type"] == "community_forum"
    assert updated.metadata["community_authority_signal"] == "staff"
    assert updated.confidence == 0.88


def test_snippet_only_source_is_capped_and_marked() -> None:
    candidate = SourceCandidate(
        title="Cursor pricing reddit",
        url="https://reddit.com/r/cursor/comments/abc",
        snippet="Cursor Pro is reported as $20 per month by several users.",
        origin="community_search",
        competitor="Cursor",
        dimension="pricing",
        confidence=0.74,
        rank=1,
        query="Cursor pricing usage limit reddit",
    )

    source = snippet_only_source_from_candidate(candidate, run_id="run-1")

    assert source is not None
    assert source.source_type == "snippet_only"
    assert source.confidence == 0.55
    assert source.metadata["community_evidence"] is True
    assert source.metadata["snippet_only"] is True
    assert source.metadata["community_source_type"] == "reddit_thread"


def test_snippet_only_source_rejects_non_community_candidate() -> None:
    candidate = SourceCandidate(
        title="Official docs",
        url="https://docs.github.com/en/copilot",
        snippet="Official product docs.",
        origin="community_search",
        competitor="GitHub Copilot",
        dimension="feature",
        confidence=0.74,
    )

    assert snippet_only_source_from_candidate(candidate, run_id="run-1") is None
```

- [ ] **Step 2: Run the helper tests and verify they fail**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_community_source_classifier.py -q
```

Expected: FAIL because `raw_sources.py` does not exist.

- [ ] **Step 3: Implement RawSource helpers**

Create `backend/packages/community/raw_sources.py` with:

```python
from __future__ import annotations

import hashlib

from packages.community.source_classifier import classify_community_source
from packages.identity import compute_raw_source_id
from packages.research.models import SourceCandidate
from packages.schema.models import RawSource

SNIPPET_ONLY_CONFIDENCE_CAP = 0.55


def reclassify_community_source(source: RawSource, *, run_id: str) -> RawSource:
    classification = classify_community_source(
        url=str(source.url or ""),
        title=source.title,
        snippet=source.snippet,
    )
    if not classification.is_community:
        return source
    confidence = max(source.confidence, classification.base_confidence)
    source_type = classification.source_type
    metadata = {
        **source.metadata,
        "community_evidence": True,
        "community_source_type": source_type,
        "community_authority_signal": classification.authority_signal,
        "community_classification_reason": classification.reason,
        "official_commitment": False,
    }
    return source.model_copy(
        update={
            "id": compute_raw_source_id(
                source_type=source_type,
                competitor=source.competitor,
                dimension=source.dimension,
                url=str(source.url) if source.url else None,
                content_hash=source.content_hash,
                title=source.title,
                snippet=source.snippet,
                run_id=run_id,
            ),
            "source_type": source_type,
            "confidence": min(0.92, confidence),
            "metadata": metadata,
        }
    )


def snippet_only_source_from_candidate(
    candidate: SourceCandidate,
    *,
    run_id: str,
) -> RawSource | None:
    classification = classify_community_source(
        url=candidate.url,
        title=candidate.title,
        snippet=candidate.snippet,
    )
    if not classification.is_community:
        return None
    snippet = " ".join((candidate.snippet or candidate.title).split())
    if not _has_concrete_community_signal(snippet):
        return None
    content_hash = hashlib.sha256(snippet.encode("utf-8", errors="ignore")).hexdigest()[:16]
    confidence = min(
        SNIPPET_ONLY_CONFIDENCE_CAP,
        candidate.confidence,
        classification.base_confidence,
    )
    return RawSource(
        id=compute_raw_source_id(
            source_type="snippet_only",
            competitor=candidate.competitor,
            dimension=candidate.dimension,
            url=candidate.url,
            content_hash=content_hash,
            title=candidate.title,
            snippet=snippet,
            run_id=run_id,
        ),
        competitor=candidate.competitor,
        dimension=candidate.dimension,
        source_type="snippet_only",
        title=candidate.title,
        url=candidate.url,
        snippet=snippet,
        content_hash=content_hash,
        confidence=confidence,
        candidate_origin=candidate.origin,
        candidate_rank=candidate.rank,
        candidate_confidence=candidate.confidence,
        fetch_method="search_snippet_only",
        quality_score=0.0,
        failure_reason="community_fetch_unavailable_or_rejected",
        metadata={
            "community_evidence": True,
            "community_source_type": classification.source_type,
            "community_authority_signal": classification.authority_signal,
            "community_classification_reason": classification.reason,
            "community_query": candidate.query,
            "snippet_only": True,
            "official_commitment": False,
        },
    )


def _has_concrete_community_signal(snippet: str) -> bool:
    normalized = snippet.casefold()
    concrete_terms = (
        "$",
        "per month",
        "usage limit",
        "quota",
        "complaint",
        "complain",
        "switched",
        "adoption",
        "context window",
        "limitation",
        "pricing",
        "cost",
    )
    return len(snippet) >= 40 and any(term in normalized for term in concrete_terms)
```

- [ ] **Step 4: Export RawSource helpers**

Update `backend/packages/community/__init__.py` imports and `__all__`:

```python
from packages.community.raw_sources import (
    reclassify_community_source,
    snippet_only_source_from_candidate,
)
```

Add these strings to `__all__`:

```python
    "reclassify_community_source",
    "snippet_only_source_from_candidate",
```

- [ ] **Step 5: Run helper tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_community_source_classifier.py -q
```

Expected: PASS.

- [ ] **Step 6: Run ruff**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\community backend\tests\unit\test_community_source_classifier.py
```

Expected: `All checks passed!`

- [ ] **Step 7: Commit Task 4**

Run:

```powershell
git add backend/packages/community backend/tests/unit/test_community_source_classifier.py
git commit -m "feat: create community raw sources"
```

---

### Task 5: Collector Community Lane

**Files:**
- Modify: `backend/packages/config/settings.py`
- Modify: `backend/packages/schema/messages.py`
- Modify: `backend/packages/agents/collectors/logic.py`
- Modify: `backend/packages/agents/collectors/skill_tools.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add failing collector integration tests**

Append these tests near existing collector web-search tests in `backend/tests/unit/test_run_service.py`:

```python
@pytest.mark.asyncio
async def test_collector_adds_community_sources_even_when_official_sources_exist() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            pplx_api_key="pplx",
            web_search_provider="perplexity",
            collector_react_enabled=False,
            collector_target_verified_sources_per_branch=1,
            collector_search_max_results=4,
            collector_community_enabled=True,
            collector_community_queries_per_branch=2,
            collector_community_target_sources_per_branch=2,
        )
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistants",
            competitors=["Cursor"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    async def fake_trace_search(  # noqa: ANN001
        record,
        agent,
        subagent,
        query,
        max_results,
        context=None,
    ) -> list[SearchResult]:
        results_by_query = {
            "Cursor pricing plans billing usage limits AI coding assistants official source": [
                SearchResult(
                    title="Cursor pricing",
                    url="https://cursor.com/pricing",
                    snippet="Cursor pricing plans include Pro and Teams.",
                )
            ],
            "Cursor pricing usage limit reddit AI coding assistants": [
                SearchResult(
                    title="Cursor Pro usage limit thread",
                    url="https://www.reddit.com/r/cursor/comments/pro_limits",
                    snippet="Users report Cursor Pro is $20 per month and mention usage limits.",
                )
            ],
            "Cursor pricing usage limit forum AI coding assistants": [
                SearchResult(
                    title="Cursor forum pricing limits",
                    url="https://forum.cursor.com/t/pricing-limits/1",
                    snippet="A staff member explains usage limits for paid plans.",
                )
            ],
        }
        return results_by_query.get(query, [])[:max_results]

    async def fake_trace_fetch(  # noqa: ANN001
        record,
        agent,
        subagent,
        url,
        context=None,
    ) -> EvidenceFetchResult:
        text_by_url = {
            "https://cursor.com/pricing": "Cursor pricing plans include Pro, Teams, billing, and usage.",
            "https://www.reddit.com/r/cursor/comments/pro_limits": "Users report Cursor Pro is $20 per month and mention usage limits.",
            "https://forum.cursor.com/t/pricing-limits/1": "A staff member explains usage limits for paid plans.",
        }
        text = text_by_url[url]
        return EvidenceFetchResult(
            url=url,
            ok=True,
            title=f"Fetched {url}",
            text=text,
            content_hash=f"hash-{len(text)}",
            status_code=200,
            fetch_method="test_fetch",
            quality_score=0.95,
            text_length=len(text),
        )

    service._trace_search = fake_trace_search  # type: ignore[method-assign]
    service._trace_fetch = fake_trace_fetch  # type: ignore[method-assign]

    await service._real_collector_branch_step(record, "pricing", "Cursor")

    source_types = {source.source_type for source in record.detail.raw_sources}
    assert "webpage_verified" in source_types
    assert {"reddit_thread", "community_forum"} & source_types
    assert any(source.metadata.get("community_evidence") for source in record.detail.raw_sources)


@pytest.mark.asyncio
async def test_collector_keeps_useful_community_snippet_when_fetch_fails() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            pplx_api_key="pplx",
            web_search_provider="perplexity",
            collector_react_enabled=False,
            collector_target_verified_sources_per_branch=1,
            collector_search_max_results=4,
            collector_community_enabled=True,
            collector_community_queries_per_branch=1,
            collector_community_target_sources_per_branch=1,
        )
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistants",
            competitors=["Cursor"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    async def fake_trace_search(  # noqa: ANN001
        record,
        agent,
        subagent,
        query,
        max_results,
        context=None,
    ) -> list[SearchResult]:
        results_by_query = {
            "Cursor pricing plans billing usage limits AI coding assistants official source": [
                SearchResult(
                    title="Cursor pricing",
                    url="https://cursor.com/pricing",
                    snippet="Cursor pricing plans include Pro.",
                )
            ],
            "Cursor pricing usage limit reddit AI coding assistants": [
                SearchResult(
                    title="Cursor Pro reported pricing",
                    url="https://www.reddit.com/r/cursor/comments/pro_limits",
                    snippet="Users report Cursor Pro is $20 per month with usage limit confusion.",
                )
            ],
        }
        return results_by_query.get(query, [])[:max_results]

    async def fake_trace_fetch(  # noqa: ANN001
        record,
        agent,
        subagent,
        url,
        context=None,
    ) -> EvidenceFetchResult:
        if url == "https://www.reddit.com/r/cursor/comments/pro_limits":
            return EvidenceFetchResult(
                url=url,
                ok=False,
                title="blocked",
                text="",
                content_hash="blocked-hash",
                status_code=403,
                error="robots blocked",
                fetch_method="test_failed_fetch",
                quality_score=0.0,
                text_length=0,
                failure_reason="robots_blocked",
            )
        return EvidenceFetchResult(
            url=url,
            ok=True,
            title="Cursor pricing",
            text="Cursor pricing plans include Pro.",
            content_hash="official-hash",
            status_code=200,
            fetch_method="test_fetch",
            quality_score=0.95,
            text_length=32,
        )

    service._trace_search = fake_trace_search  # type: ignore[method-assign]
    service._trace_fetch = fake_trace_fetch  # type: ignore[method-assign]

    await service._real_collector_branch_step(record, "pricing", "Cursor")

    snippet_sources = [
        source for source in record.detail.raw_sources if source.source_type == "snippet_only"
    ]
    assert len(snippet_sources) == 1
    assert snippet_sources[0].confidence == 0.55
    assert snippet_sources[0].metadata["community_source_type"] == "reddit_thread"


@pytest.mark.asyncio
async def test_collector_records_no_result_metadata_for_empty_community_search() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            pplx_api_key="pplx",
            web_search_provider="perplexity",
            collector_react_enabled=False,
            collector_target_verified_sources_per_branch=1,
            collector_search_max_results=4,
            collector_community_enabled=True,
            collector_community_queries_per_branch=1,
            collector_community_target_sources_per_branch=1,
        )
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistants",
            competitors=["Cursor"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    async def fake_trace_search(  # noqa: ANN001
        record,
        agent,
        subagent,
        query,
        max_results,
        context=None,
    ) -> list[SearchResult]:
        if query == "Cursor pricing plans billing usage limits AI coding assistants official source":
            return [
                SearchResult(
                    title="Cursor pricing",
                    url="https://cursor.com/pricing",
                    snippet="Cursor pricing plans include Pro.",
                )
            ]
        return []

    async def fake_trace_fetch(  # noqa: ANN001
        record,
        agent,
        subagent,
        url,
        context=None,
    ) -> EvidenceFetchResult:
        return EvidenceFetchResult(
            url=url,
            ok=True,
            title="Cursor pricing",
            text="Cursor pricing plans include Pro.",
            content_hash="official-hash",
            status_code=200,
            fetch_method="test_fetch",
            quality_score=0.95,
            text_length=32,
        )

    service._trace_search = fake_trace_search  # type: ignore[method-assign]
    service._trace_fetch = fake_trace_fetch  # type: ignore[method-assign]

    await service._real_collector_branch_step(record, "pricing", "Cursor")

    community_messages = [
        message
        for message in record.detail.agent_messages
        if message.message_type == "community_search_completed"
    ]
    assert len(community_messages) == 1
    assert community_messages[0].payload["candidate_count"] == 0
    assert community_messages[0].payload["no_result"] is True
```

- [ ] **Step 2: Run collector tests and verify they fail**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -k "community_sources_even_when_official or community_snippet_when_fetch_fails or no_result_metadata_for_empty_community_search" -q
```

Expected: FAIL because settings and collector community lane do not exist.

- [ ] **Step 3: Add community collector settings**

In `backend/packages/config/settings.py`, add fields near existing collector settings:

```python
    collector_community_enabled: bool = True
    collector_community_queries_per_branch: int = 3
    collector_community_max_results_per_query: int = 5
    collector_community_target_sources_per_branch: int = 2
```

In `load_settings()`, add:

```python
        collector_community_enabled=_env_bool(
            "COLLECTOR_COMMUNITY_ENABLED",
            True,
        ),
        collector_community_queries_per_branch=_env_int(
            "COLLECTOR_COMMUNITY_QUERIES_PER_BRANCH",
            3,
            minimum=0,
            maximum=10,
        ),
        collector_community_max_results_per_query=_env_int(
            "COLLECTOR_COMMUNITY_MAX_RESULTS_PER_QUERY",
            5,
            minimum=1,
            maximum=20,
        ),
        collector_community_target_sources_per_branch=_env_int(
            "COLLECTOR_COMMUNITY_TARGET_SOURCES_PER_BRANCH",
            2,
            minimum=0,
            maximum=6,
        ),
```

- [ ] **Step 4: Add community search message schema**

In `backend/packages/schema/messages.py`, add this payload model after `RawSourceDigestMessagePayload`:

```python
class CommunitySearchSummaryMessagePayload(_MessagePayload):
    competitor: str
    dimension: str
    queries: list[str] = Field(default_factory=list)
    query_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    candidate_ids: list[str] = Field(default_factory=list)
    no_result: bool = False
```

Register it in `AGENT_MESSAGE_PAYLOAD_SCHEMAS`:

```python
    "CommunitySearchSummary": CommunitySearchSummaryMessagePayload,
```

- [ ] **Step 5: Add collector imports**

In `backend/packages/agents/collectors/logic.py`, add imports:

```python
from packages.community import (
    build_community_queries,
    reclassify_community_source,
    snippet_only_source_from_candidate,
)
from packages.community.source_classifier import classify_community_source
```

- [ ] **Step 6: Add community candidate builder helper**

In `CollectorAgentMixin`, near `_web_search_query()`, add:

```python
    async def _community_source_candidates(
        self,
        record: RunRecord,
        detail: RunDetail,
        dimension: str,
        competitor: str,
        context: SubagentContext,
    ) -> list[SourceCandidate]:
        if not self._settings.collector_community_enabled or not self._search.is_enabled:
            return []
        queries = build_community_queries(
            competitor=competitor,
            dimension=dimension,
            topic=detail.topic,
            limit=max(0, int(self._settings.collector_community_queries_per_branch)),
        )
        candidates: list[SourceCandidate] = []
        for query in queries:
            results = await self._trace_search(
                record,
                agent="collector",
                subagent=context.subagent,
                query=query,
                max_results=max(1, int(self._settings.collector_community_max_results_per_query)),
                context=context,
            )
            for rank, result in enumerate(results):
                classification = classify_community_source(
                    url=result.url,
                    title=result.title,
                    snippet=result.snippet,
                )
                if not classification.is_community:
                    continue
                candidates.append(
                    SourceCandidate(
                        title=result.title,
                        url=result.url,
                        snippet=result.snippet,
                        origin="community_search",
                        competitor=competitor,
                        dimension=dimension,
                        rank=rank,
                        confidence=classification.base_confidence,
                        query=query,
                        date=result.date,
                        last_updated=result.last_updated,
                        reason="community_evidence_search",
                        metadata={
                            "community_evidence": True,
                            "community_source_type": classification.source_type,
                            "community_authority_signal": classification.authority_signal,
                            "community_classification_reason": classification.reason,
                        },
                    )
                )
        self._append_agent_message(
            record,
            from_agent="collector",
            to_agent="collect_join",
            message_type="community_search_completed",
            payload_schema="CommunitySearchSummary",
            payload={
                "competitor": competitor,
                "dimension": dimension,
                "queries": queries,
                "query_count": len(queries),
                "candidate_count": len(candidates),
                "candidate_ids": [candidate.id for candidate in candidates],
                "no_result": not candidates,
            },
        )
        return candidates
```

- [ ] **Step 7: Add community source collection helper**

In `CollectorAgentMixin`, below `_community_source_candidates()`, add:

```python
    async def _collect_community_sources_for_branch(
        self,
        record: RunRecord,
        detail: RunDetail,
        dimension: str,
        competitor: str,
        context: SubagentContext,
    ) -> list[RawSource]:
        candidates = await self._community_source_candidates(
            record,
            detail,
            dimension,
            competitor,
            context,
        )
        if not candidates:
            return []
        target_count = max(0, int(self._settings.collector_community_target_sources_per_branch))
        if target_count <= 0:
            return []
        fetched_sources = await self._collect_competitor_with_research_pipeline(
            record,
            detail,
            dimension,
            competitor,
            context,
            batch_sources=[],
            target_source_count=target_count,
            include_official=False,
            seed_candidates=candidates,
            enable_search=False,
            enable_repair=False,
        )
        community_sources = [
            reclassify_community_source(source, run_id=detail.id)
            for source in fetched_sources
        ]
        if len(community_sources) < target_count:
            existing_urls = {
                str(source.url).rstrip("/")
                for source in community_sources
                if source.url is not None
            }
            for candidate in candidates:
                if len(community_sources) >= target_count:
                    break
                if candidate.url.rstrip("/") in existing_urls:
                    continue
                snippet_source = snippet_only_source_from_candidate(candidate, run_id=detail.id)
                if snippet_source is None:
                    continue
                community_sources.append(snippet_source)
                existing_urls.add(candidate.url.rstrip("/"))
        return [
            source
            for source in community_sources
            if not self._candidate_already_collected(
                detail,
                [],
                competitor=competitor,
                dimension=dimension,
                url=str(source.url) if source.url else None,
            )
        ]
```

- [ ] **Step 8: Wire the helper into branch collection**

In `_real_collector_branch_step()`, after the existing deterministic source collection has filled local `sources` and before `detail.raw_sources.extend(sources)`, add:

```python
        community_sources = await self._collect_community_sources_for_branch(
            record,
            detail,
            dimension,
            competitor,
            context,
        )
        for source in community_sources:
            if not self._source_already_in_batch(source, sources):
                sources.append(source)
        collect_payload["community_source_count"] = len(community_sources)
        collect_payload["community_source_ids"] = [source.id for source in community_sources]
```

- [ ] **Step 9: Make `search_review_site` execute community search in skill tools**

In `backend/packages/agents/collectors/skill_tools.py`, replace the `if not sources and "search_review_site"` guard with:

```python
    if "search_review_site" in allowlist and service._search.is_enabled:
```

Inside that branch, after tracing the review plan and before the existing per-query loop, add:

```python
        community_sources = await service._collect_community_sources_for_branch(
            record,
            detail,
            dimension,
            competitor,
            context,
        )
        if community_sources:
            sources.extend(community_sources)
            return sources
```

Keep the existing legacy loop after this block so older review-site behavior remains as a fallback.

- [ ] **Step 10: Consume community search summaries in collect join**

In `_real_collect_join_step()` in `backend/packages/agents/collectors/logic.py`, add `"community_search_completed"` to both collect-join `message_types` sets:

```python
                "raw_sources_collected",
                "cross_competitor_sources_collected",
                "cross_competitor_search_failed",
                "community_search_completed",
```

- [ ] **Step 11: Run collector tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -k "community_sources_even_when_official or community_snippet_when_fetch_fails or no_result_metadata_for_empty_community_search" -q
```

Expected: PASS.

- [ ] **Step 12: Run ruff for collector files**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\config\settings.py backend\packages\schema\messages.py backend\packages\agents\collectors\logic.py backend\packages\agents\collectors\skill_tools.py backend\tests\unit\test_run_service.py
```

Expected: `All checks passed!`

- [ ] **Step 13: Commit Task 5**

Run:

```powershell
git add backend/packages/config/settings.py backend/packages/schema/messages.py backend/packages/agents/collectors/logic.py backend/packages/agents/collectors/skill_tools.py backend/tests/unit/test_run_service.py
git commit -m "feat: collect community evidence"
```

---

### Task 6: Collect Join Cluster Annotation And Analyst Consumption

**Files:**
- Modify: `backend/packages/agents/collectors/logic.py`
- Modify: `backend/packages/agents/analysts/logic.py`
- Modify: `backend/packages/agents/comparator/logic.py`
- Modify: `backend/tests/unit/test_run_service.py`
- Modify: `backend/tests/unit/test_review_theme_summary.py`

- [ ] **Step 1: Add failing collect-join cluster metadata test**

Append to `backend/tests/unit/test_run_service.py`:

```python
def test_collect_join_annotates_community_claim_clusters() -> None:
    service = RunService(
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        )
    )
    detail = RunDetail(
        id="run-community-clusters",
        topic="AI coding assistants",
        status="running",
        execution_mode="real",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="AI coding assistants",
            competitors=["Cursor"],
            dimensions=["pricing"],
        ),
    )
    record = RunRecord(detail=detail)
    record.detail.raw_sources = [
        RawSource(
            id="reddit-cursor-pricing",
            competitor="Cursor",
            dimension="pricing",
            source_type="reddit_thread",
            title="Cursor pricing reddit",
            url="https://reddit.com/r/cursor/comments/abc",
            snippet="Cursor Pro is $20 per month.",
            content_hash="reddit-hash",
            confidence=0.62,
            metadata={"community_evidence": True, "community_source_type": "reddit_thread"},
        ),
        RawSource(
            id="forum-cursor-pricing",
            competitor="Cursor",
            dimension="pricing",
            source_type="community_forum",
            title="Cursor pricing forum",
            url="https://forum.cursor.com/t/pricing/1",
            snippet="Cursor Pro price is $20 per month.",
            content_hash="forum-hash",
            confidence=0.78,
            metadata={"community_evidence": True, "community_source_type": "community_forum"},
        ),
    ]

    service._annotate_community_claim_clusters(record.detail, ["pricing"])

    clusters = record.detail.raw_sources[0].metadata["community_claim_clusters"]
    assert clusters[0]["label"] == "community_triangulated"
    assert clusters[0]["confidence"] >= 0.70
    assert clusters[0]["source_ids"] == ["reddit-cursor-pricing", "forum-cursor-pricing"]


def test_collect_join_marks_community_cluster_official_confirmed_when_values_match() -> None:
    service = RunService(
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        )
    )
    detail = RunDetail(
        id="run-community-official-confirmed",
        topic="AI coding assistants",
        status="running",
        execution_mode="real",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="AI coding assistants",
            competitors=["Cursor"],
            dimensions=["pricing"],
        ),
        raw_sources=[
            RawSource(
                id="cursor-official-pricing",
                competitor="Cursor",
                dimension="pricing",
                source_type="webpage_verified",
                title="Cursor pricing",
                url="https://cursor.com/pricing",
                snippet="Cursor Pro is $20 per month.",
                content_hash="official-hash",
                confidence=0.92,
            ),
            RawSource(
                id="reddit-cursor-pricing",
                competitor="Cursor",
                dimension="pricing",
                source_type="reddit_thread",
                title="Cursor pricing reddit",
                url="https://reddit.com/r/cursor/comments/abc",
                snippet="Cursor Pro is $20 per month.",
                content_hash="reddit-hash",
                confidence=0.62,
                metadata={"community_evidence": True, "community_source_type": "reddit_thread"},
            ),
        ],
    )

    service._annotate_community_claim_clusters(detail, ["pricing"])

    clusters = detail.raw_sources[1].metadata["community_claim_clusters"]
    assert clusters[0]["label"] == "official_confirmed"
    assert clusters[0]["confidence"] >= 0.95
    assert clusters[0]["official_source_ids"] == ["cursor-official-pricing"]
    assert clusters[0]["source_ids"] == ["reddit-cursor-pricing", "cursor-official-pricing"]
```

- [ ] **Step 2: Add failing analyst review-summary test**

Append to `backend/tests/unit/test_review_theme_summary.py`:

```python
def test_review_summary_uses_community_clusters_for_review_dimension() -> None:
    service = RunService(
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        )
    )
    detail = RunDetail(
        id="run-community-review-summary",
        topic="AI coding assistants",
        status="running",
        execution_mode="real",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="AI coding assistants",
            competitors=["Cursor"],
            dimensions=["review"],
        ),
        raw_sources=[
            RawSource(
                id="reddit-complaint",
                competitor="Cursor",
                dimension="review",
                source_type="reddit_thread",
                title="Cursor complaint thread",
                url="https://reddit.com/r/cursor/comments/complaint",
                snippet="Users complain about pricing confusion and adoption friction.",
                content_hash="reddit-complaint-hash",
                confidence=0.68,
                metadata={
                    "community_evidence": True,
                    "community_claim_clusters": [
                        {
                            "kind": "complaint",
                            "label": "community_observed",
                            "claim": "Users report pricing confusion.",
                            "source_ids": ["reddit-complaint"],
                            "confidence": 0.68,
                            "evidence": ["Users complain about pricing confusion."],
                        }
                    ],
                },
            )
        ],
    )

    service._merge_structured_knowledge_slice(
        detail,
        competitor="Cursor",
        dimension="review",
        findings=["Users report pricing confusion. [source:reddit-complaint]"],
    )

    summary = detail.competitor_knowledge["Cursor"].review_summary
    assert summary.complaint_themes
    assert summary.complaint_themes[0].source_ids == ["reddit-complaint"]
    assert summary.complaint_themes[0].confidence == 0.68
```

- [ ] **Step 3: Add failing comparator official-winner guard test**

Append to `backend/tests/unit/test_run_service.py`:

```python
def test_comparison_matrix_keeps_community_sources_out_of_official_winner_signal() -> None:
    service = RunService(
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        )
    )
    detail = RunDetail(
        id="run-community-comparator-guard",
        topic="AI coding assistants",
        status="running",
        execution_mode="real",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="AI coding assistants",
            competitors=["Cursor", "GitHub Copilot"],
            dimensions=["pricing"],
        ),
        raw_sources=[
            RawSource(
                id="cursor-reddit-pricing",
                competitor="Cursor",
                dimension="pricing",
                source_type="reddit_thread",
                title="Cursor pricing reddit",
                url="https://reddit.com/r/cursor/comments/pricing",
                snippet="Users report Cursor Pro pricing and usage-limit caveats.",
                content_hash="cursor-reddit-hash",
                confidence=0.90,
                metadata={
                    "community_evidence": True,
                    "community_source_type": "reddit_thread",
                    "community_claim_clusters": [
                        {
                            "kind": "pricing",
                            "label": "community_triangulated",
                            "claim": "Community sources report pricing caveats.",
                            "source_ids": ["cursor-reddit-pricing", "cursor-forum-pricing"],
                            "confidence": 0.90,
                            "evidence": ["Users report Cursor pricing caveats."],
                        }
                    ],
                },
            ),
            RawSource(
                id="cursor-forum-pricing",
                competitor="Cursor",
                dimension="pricing",
                source_type="community_forum",
                title="Cursor pricing forum",
                url="https://forum.cursor.com/t/pricing",
                snippet="Forum users discuss pricing caveats and quotas.",
                content_hash="cursor-forum-hash",
                confidence=0.88,
                metadata={"community_evidence": True, "community_source_type": "community_forum"},
            ),
            RawSource(
                id="copilot-official-pricing",
                competitor="GitHub Copilot",
                dimension="pricing",
                source_type="webpage_verified",
                title="GitHub Copilot pricing",
                url="https://github.com/features/copilot#pricing",
                snippet="GitHub Copilot official pricing is published.",
                content_hash="copilot-official-hash",
                confidence=0.84,
            ),
        ],
    )

    matrix = service._build_comparison_matrix(detail, {"matrix_summary": []})

    assert matrix.winner_by_dimension["pricing"] == "GitHub Copilot"
    assert any("[community-adjusted:pricing]" in item for item in matrix.summary)
    assert any("community_triangulated" in item for item in matrix.summary)
```

- [ ] **Step 4: Run focused tests and verify they fail**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_collect_join_annotates_community_claim_clusters backend\tests\unit\test_run_service.py::test_collect_join_marks_community_cluster_official_confirmed_when_values_match backend\tests\unit\test_run_service.py::test_comparison_matrix_keeps_community_sources_out_of_official_winner_signal backend\tests\unit\test_review_theme_summary.py::test_review_summary_uses_community_clusters_for_review_dimension -q
```

Expected: FAIL because annotation, analyst consumption, and comparator community-vs-official winner separation are not implemented.

- [ ] **Step 5: Add collect-join annotation helper**

In `backend/packages/agents/collectors/logic.py`, import:

```python
from packages.community import (
    CommunityClaimCluster,
    build_community_queries,
    cluster_community_claims,
    extract_community_claims_from_source,
    reclassify_community_source,
    snippet_only_source_from_candidate,
)
from packages.refs import merge_ordered_refs
```

Add this helper near `_normalize_collected_sources()`:

```python
    def _annotate_community_claim_clusters(
        self,
        detail: RunDetail,
        dimensions: list[str],
    ) -> None:
        scoped_dimensions = set(dimensions)
        claims = [
            claim
            for source in detail.raw_sources
            if (not scoped_dimensions or source.dimension in scoped_dimensions)
            for claim in extract_community_claims_from_source(source)
        ]
        clusters = cluster_community_claims(claims)
        clusters_by_source_id: dict[str, list[dict[str, object]]] = {}
        for cluster in clusters:
            payload = cluster.model_dump(mode="json")
            official_source_ids = self._official_confirmation_source_ids(detail, cluster)
            if official_source_ids:
                payload["label"] = "official_confirmed"
                payload["confidence"] = max(float(payload.get("confidence") or 0.0), 0.95)
                payload["official_source_ids"] = official_source_ids
                payload["source_ids"] = merge_ordered_refs(
                    payload.get("source_ids", []),
                    official_source_ids,
                )
            for source_id in cluster.source_ids:
                clusters_by_source_id.setdefault(source_id, []).append(payload)
        updated_sources: list[RawSource] = []
        for source in detail.raw_sources:
            source_clusters = clusters_by_source_id.get(source.id)
            if not source_clusters:
                updated_sources.append(source)
                continue
            metadata = dict(source.metadata)
            metadata["community_claim_clusters"] = source_clusters
            updated_sources.append(source.model_copy(update={"metadata": metadata}))
        detail.raw_sources = updated_sources

    def _official_confirmation_source_ids(
        self,
        detail: RunDetail,
        cluster: CommunityClaimCluster,
    ) -> list[str]:
        if not cluster.normalized_value:
            return []
        normalized_value = cluster.normalized_value.casefold()
        return [
            source.id
            for source in detail.raw_sources
            if source.competitor == cluster.competitor
            and source.dimension == cluster.dimension
            and source.source_type == "webpage_verified"
            and normalized_value in source.snippet.casefold()
        ]
```

- [ ] **Step 6: Call annotation from collect join**

In `_real_collect_join_step()`, after:

```python
        detail.raw_sources = self._normalize_collected_sources(detail, dimensions)
```

add:

```python
        self._annotate_community_claim_clusters(detail, dimensions)
```

- [ ] **Step 7: Add analyst helper for community clusters**

In `backend/packages/agents/analysts/logic.py`, add this helper near `_build_review_summary_from_source_dicts()`:

```python
    def _build_review_summary_from_community_clusters(
        self,
        *,
        competitor: str,
        dimension: str,
        sources: list[dict[str, Any]],
    ) -> ReviewThemeSummary:
        summary = ReviewThemeSummary(competitor=competitor, dimension=dimension)
        for source in sources:
            metadata = source.get("metadata")
            if not isinstance(metadata, dict):
                continue
            clusters = metadata.get("community_claim_clusters")
            if not isinstance(clusters, list):
                continue
            for cluster in clusters:
                if not isinstance(cluster, dict):
                    continue
                item = self._community_review_theme_item(cluster)
                kind = str(cluster.get("kind") or "")
                if kind == "praise":
                    summary.praise_themes.append(item)
                elif kind == "complaint":
                    summary.complaint_themes.append(item)
                elif kind == "adoption_blocker":
                    summary.adoption_blockers.append(item)
                elif kind == "switching_trigger":
                    summary.switching_triggers.append(item)
                elif kind in {"usage_limit", "feature_limitation"}:
                    summary.complaint_themes.append(item)
        summary.source_ids = merge_ordered_refs(
            source_id
            for item in (
                *summary.praise_themes,
                *summary.complaint_themes,
                *summary.adoption_blockers,
                *summary.switching_triggers,
            )
            for source_id in item.source_ids
        )
        confidences = [
            item.confidence
            for item in (
                *summary.praise_themes,
                *summary.complaint_themes,
                *summary.adoption_blockers,
                *summary.switching_triggers,
            )
        ]
        if confidences:
            summary.confidence = max(confidences)
            summary.sentiment_hint = self._review_sentiment_hint(
                bool(summary.praise_themes),
                bool(summary.complaint_themes or summary.adoption_blockers),
            )
        return summary

    def _community_review_theme_item(self, cluster: dict[str, Any]) -> ReviewThemeItem:
        source_ids = [
            str(source_id)
            for source_id in cluster.get("source_ids", [])
            if str(source_id).strip()
        ]
        evidence_list = cluster.get("evidence", [])
        evidence = (
            str(evidence_list[0])
            if isinstance(evidence_list, list) and evidence_list
            else str(cluster.get("claim") or "")
        )
        return ReviewThemeItem(
            theme=str(cluster.get("claim") or "Community observation"),
            evidence=evidence,
            source_ids=source_ids,
            confidence=self._coerce_confidence(cluster.get("confidence"), default=0.55),
            evidence_gap=not source_ids,
        )
```

- [ ] **Step 8: Prefer community cluster review summaries when available**

In both places where `_build_review_summary_from_source_dicts()` is called for review/persona dimensions, replace the direct assignment with:

```python
            community_summary = self._build_review_summary_from_community_clusters(
                competitor=competitor,
                dimension=dimension,
                sources=review_sources,
            )
            if self._review_summary_has_cited_items(community_summary):
                knowledge.review_summary = community_summary
            else:
                knowledge.review_summary = self._build_review_summary_from_source_dicts(
                    competitor=competitor,
                    dimension=dimension,
                    sources=review_sources,
                )
```

Apply this replacement in `_merge_structured_knowledge_slice()` and `_merge_structured_knowledge_payload()` where `review_sources` is already computed.

- [ ] **Step 9: Add comparator community caveats without official winner leakage**

In `backend/packages/agents/comparator/logic.py`, add this constant near `FEATURE_TAXONOMY_ORDER`:

```python
COMMUNITY_MATRIX_SOURCE_TYPES = {
    "community_forum",
    "reddit_thread",
    "github_discussion",
    "github_issue",
    "review_site",
    "developer_blog",
    "snippet_only",
}
```

In `_build_comparison_matrix()`, add community summaries before payload summaries:

```python
            summary=[
                *self._matrix_standardization_summary(detail),
                *self._community_matrix_summary(detail),
                *self._string_list(payload.get("matrix_summary")),
                *vote_summary,
            ],
```

In `_matrix_majority_vote()`, create a source lookup before the dimension loop:

```python
        source_by_id = {source.id: source for source in detail.raw_sources}
```

Replace the existing `evidence_winner` and `confidence_winner` score inputs with official-only scores:

```python
            evidence_winner = self._winner_from_numeric_signal(
                {
                    competitor: self._official_matrix_source_count(
                        self._matrix_cell(cell_by_key, dimension, competitor),
                        source_by_id,
                    )
                    for competitor in detail.plan.competitors
                }
            )
            confidence_winner = self._winner_from_numeric_signal(
                {
                    competitor: self._official_matrix_confidence(
                        self._matrix_cell(cell_by_key, dimension, competitor),
                        source_by_id,
                    )
                    for competitor in detail.plan.competitors
                }
            )
```

Add these helpers near `_matrix_cell()`:

```python
    def _official_matrix_source_count(
        self,
        cell: ComparisonCell,
        source_by_id: dict[str, RawSource],
    ) -> int:
        return sum(
            1
            for source_id in cell.source_ids
            if self._matrix_source_is_official_signal(source_by_id.get(source_id))
        )

    def _official_matrix_confidence(
        self,
        cell: ComparisonCell,
        source_by_id: dict[str, RawSource],
    ) -> float:
        confidences = [
            source.confidence
            for source_id in cell.source_ids
            for source in [source_by_id.get(source_id)]
            if self._matrix_source_is_official_signal(source)
        ]
        return max(confidences, default=0.0)

    def _matrix_source_is_official_signal(self, source: RawSource | None) -> bool:
        if source is None:
            return False
        if source.metadata.get("community_evidence"):
            return False
        return source.source_type not in COMMUNITY_MATRIX_SOURCE_TYPES

    def _community_matrix_summary(self, detail: RunDetail) -> list[str]:
        summaries: list[str] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for source in detail.raw_sources:
            if not source.metadata.get("community_evidence"):
                continue
            clusters = source.metadata.get("community_claim_clusters")
            if not isinstance(clusters, list):
                continue
            for cluster in clusters:
                if not isinstance(cluster, dict):
                    continue
                label = str(cluster.get("label") or "")
                if label not in {
                    "official_confirmed",
                    "community_triangulated",
                    "community_observed",
                    "community_contested",
                }:
                    continue
                kind = str(cluster.get("kind") or "")
                normalized_value = str(cluster.get("normalized_value") or "")
                claim = str(cluster.get("claim") or "Community observation")
                key = (source.dimension, source.competitor, kind, normalized_value, label)
                if key in seen:
                    continue
                seen.add(key)
                source_ids = [
                    str(source_id)
                    for source_id in cluster.get("source_ids", [])
                    if str(source_id).strip()
                ]
                summaries.append(
                    "[community-adjusted:{dimension}] {competitor}: {label}; "
                    "{claim} sources={sources}".format(
                        dimension=source.dimension,
                        competitor=source.competitor,
                        label=label,
                        claim=claim,
                        sources=", ".join(source_ids[:4]),
                    )
                )
        return summaries[:8]
```

- [ ] **Step 10: Run focused tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_collect_join_annotates_community_claim_clusters backend\tests\unit\test_run_service.py::test_collect_join_marks_community_cluster_official_confirmed_when_values_match backend\tests\unit\test_run_service.py::test_comparison_matrix_keeps_community_sources_out_of_official_winner_signal backend\tests\unit\test_review_theme_summary.py::test_review_summary_uses_community_clusters_for_review_dimension -q
```

Expected: PASS.

- [ ] **Step 11: Run ruff**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\agents\collectors\logic.py backend\packages\agents\analysts\logic.py backend\packages\agents\comparator\logic.py backend\tests\unit\test_run_service.py backend\tests\unit\test_review_theme_summary.py
```

Expected: `All checks passed!`

- [ ] **Step 12: Commit Task 6**

Run:

```powershell
git add backend/packages/agents/collectors/logic.py backend/packages/agents/analysts/logic.py backend/packages/agents/comparator/logic.py backend/tests/unit/test_run_service.py backend/tests/unit/test_review_theme_summary.py
git commit -m "feat: annotate community claim clusters"
```

---

### Task 7: Writer Context And Report Contract

**Files:**
- Modify: `backend/packages/i18n/language.py`
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add failing writer context test**

Append to `backend/tests/unit/test_run_service.py` near source digest tests:

```python
def test_writer_source_digest_exposes_community_metadata() -> None:
    service = RunService(
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        )
    )
    source = RawSource(
        id="reddit-cursor-pricing",
        competitor="Cursor",
        dimension="pricing",
        source_type="reddit_thread",
        title="Cursor pricing reddit",
        url="https://reddit.com/r/cursor/comments/abc",
        snippet="Cursor Pro is $20 per month.",
        content_hash="hash",
        confidence=0.62,
        metadata={
            "community_evidence": True,
            "community_source_type": "reddit_thread",
            "community_authority_signal": "user",
            "official_commitment": False,
            "community_claim_clusters": [
                {
                    "kind": "pricing",
                    "label": "community_observed",
                    "claim": "Community sources report pricing at $20 per month.",
                    "source_ids": ["reddit-cursor-pricing"],
                    "confidence": 0.62,
                    "evidence": ["Cursor Pro is $20 per month."],
                }
            ],
        },
    )

    digest = service._writer_source_digest([source])

    assert digest[0]["source_type"] == "reddit_thread"
    assert digest[0]["community_evidence"] is True
    assert digest[0]["official_commitment"] is False
    assert digest[0]["community_claim_clusters"][0]["label"] == "community_observed"
```

- [ ] **Step 2: Add failing writer prompt contract test**

In `test_writer_uses_compact_context_package_for_llm_prompt`, add a second raw source to `record.detail.raw_sources` so the conditional community report section is required:

```python
        RawSource(
            id="community-pricing-a",
            competitor="A",
            dimension="pricing",
            source_type="reddit_thread",
            title="A pricing community thread",
            url="https://reddit.com/r/a/comments/pricing",
            snippet="Community users report practical pricing caveats and usage limits.",
            content_hash="community-pricing-a-hash",
            confidence=0.68,
            metadata={"community_evidence": True, "community_source_type": "reddit_thread"},
        ),
```

Then add these assertions after the existing `captured_user` assertions:

```python
    assert "Official facts vs community observations" in captured_user
    assert "Do not present community observations as official commitments" in captured_user
    assert "Community Evidence Triangulation" in captured_user
```

- [ ] **Step 3: Run writer tests and verify they fail**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -k "writer_source_digest_exposes_community_metadata or writer_uses_compact_context_package" -q
```

Expected: FAIL because writer digest and prompt do not expose the new contract.

- [ ] **Step 4: Add community metadata to source digest**

In `_writer_source_digest()` in `backend/packages/agents/writer/logic.py`, after normalized fields are added, insert:

```python
            if source.metadata.get("community_evidence"):
                digest["community_evidence"] = True
                digest["community_source_type"] = source.metadata.get("community_source_type")
                digest["community_authority_signal"] = source.metadata.get(
                    "community_authority_signal"
                )
                digest["official_commitment"] = bool(
                    source.metadata.get("official_commitment", False)
                )
                clusters = source.metadata.get("community_claim_clusters")
                if isinstance(clusters, list):
                    digest["community_claim_clusters"] = clusters[:5]
```

- [ ] **Step 5: Add localized report label**

In `backend/packages/i18n/language.py`, add this key to both `REPORT_LABELS` dictionaries:

```python
        "community_evidence_triangulation": "\u793e\u533a\u8bc1\u636e\u4e09\u89d2\u9a8c\u8bc1",
```

```python
        "community_evidence_triangulation": "Community Evidence Triangulation",
```

- [ ] **Step 6: Add writer report section requirement**

In `_writer_required_sections()` in `backend/packages/agents/writer/logic.py`, add this section to the core analysis layer when any raw source has `metadata["community_evidence"]`:

```python
        if any(source.metadata.get("community_evidence") for source in detail.raw_sources):
            analysis_sections.append(
                f"{report_label(output_language, 'community_evidence_triangulation')}: "
                "separate official facts from community observations, contested claims, "
                "and actual-use risks."
            )
```

- [ ] **Step 7: Add prompt policy language**

In the writer user prompt where required sections and writer context are sent, add this sentence near the existing evidence policy text:

```python
                            "Official facts vs community observations: official docs may support official commitments; community_triangulated, community_observed, and community_contested clusters may support actual-use risks, user evaluation, and pricing caveats. Do not present community observations as official commitments unless an official source also supports the same claim.\n"
```

- [ ] **Step 8: Run writer tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -k "writer_source_digest_exposes_community_metadata or writer_uses_compact_context_package" -q
```

Expected: PASS.

- [ ] **Step 9: Run ruff**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\i18n\language.py backend\packages\agents\writer\logic.py backend\tests\unit\test_run_service.py
```

Expected: `All checks passed!`

- [ ] **Step 10: Commit Task 7**

Run:

```powershell
git add backend/packages/i18n/language.py backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "feat: expose community evidence to writer"
```

---

### Task 8: QA And Report Quality Guards

**Files:**
- Modify: `backend/packages/agents/qa/logic.py`
- Modify: `backend/packages/business_intel/report_quality.py`
- Modify: `backend/tests/unit/test_run_service.py`
- Modify: `backend/tests/unit/test_report_quality.py`

- [ ] **Step 1: Add failing QA tests**

Append to `backend/tests/unit/test_run_service.py`:

```python
def test_persona_strength_accepts_community_public_signal() -> None:
    service = RunService(
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        )
    )
    detail = RunDetail(
        id="run-community-persona-strength",
        topic="AI coding assistants",
        status="running",
        execution_mode="real",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="AI coding assistants",
            competitors=["Cursor"],
            dimensions=["persona"],
        ),
        raw_sources=[
            RawSource(
                id="reddit-persona",
                competitor="Cursor",
                dimension="persona",
                source_type="reddit_thread",
                title="Cursor adoption thread",
                url="https://reddit.com/r/cursor/comments/adoption",
                snippet="Developers and enterprise teams discuss onboarding and workflow fit.",
                content_hash="hash",
                confidence=0.68,
                metadata={"community_evidence": True},
            )
        ],
    )

    issues = service._build_persona_evidence_strength_issues(detail, [])

    assert issues == []


def test_collect_qa_does_not_block_typed_community_sources_as_unverified() -> None:
    service = RunService(
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        )
    )
    detail = RunDetail(
        id="run-community-source-qa",
        topic="AI coding assistants",
        status="running",
        execution_mode="real",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="AI coding assistants",
            competitors=["Cursor"],
            dimensions=["pricing"],
        ),
        raw_sources=[
            RawSource(
                id="reddit-pricing",
                competitor="Cursor",
                dimension="pricing",
                source_type="reddit_thread",
                title="Cursor pricing reddit",
                url="https://reddit.com/r/cursor/comments/pricing",
                snippet="Cursor Pro is $20 per month.",
                content_hash="hash",
                confidence=0.62,
                metadata={"community_evidence": True},
            )
        ],
        agent_messages=[
            AgentMessage(
                id="msg-community-search",
                run_id="run-community-source-qa",
                from_agent="collector",
                to_agent="collect_join",
                message_type="community_search_completed",
                payload_schema="CommunitySearchSummary",
                payload={
                    "competitor": "Cursor",
                    "dimension": "pricing",
                    "queries": ["Cursor pricing usage limit reddit AI coding assistants"],
                    "query_count": 1,
                    "candidate_count": 1,
                    "candidate_ids": ["candidate-1"],
                    "no_result": False,
                },
            )
        ],
    )

    issues = service._build_collect_qa_issues(detail)

    assert not any("not fetched webpage evidence" in issue.problem for issue in issues)


def test_qa_blocks_community_observation_written_as_official_commitment() -> None:
    service = RunService(
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        )
    )
    detail = RunDetail(
        id="run-community-official-guard",
        topic="AI coding assistants",
        status="running",
        execution_mode="real",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="AI coding assistants",
            competitors=["Cursor"],
            dimensions=["pricing"],
        ),
        raw_sources=[
            RawSource(
                id="reddit-pricing",
                competitor="Cursor",
                dimension="pricing",
                source_type="reddit_thread",
                title="Cursor pricing reddit",
                url="https://reddit.com/r/cursor/comments/pricing",
                snippet="Cursor Pro is $20 per month.",
                content_hash="hash",
                confidence=0.62,
                metadata={
                    "community_evidence": True,
                    "community_claim_clusters": [
                        {
                            "label": "community_observed",
                            "claim": "Community sources report pricing at $20 per month.",
                            "source_ids": ["reddit-pricing"],
                        }
                    ],
                },
            )
        ],
        report_md="## Pricing\nOfficial Cursor pricing is $20 per month. [source:reddit-pricing]",
    )

    issues = service._build_collect_qa_issues(detail)

    assert any(
        issue.severity == "blocker"
        and "community observation as official" in issue.problem
        for issue in issues
    )


def test_qa_warns_when_community_triangulation_was_not_attempted() -> None:
    service = RunService(
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        )
    )
    detail = RunDetail(
        id="run-community-missing-attempt",
        topic="AI coding assistants",
        status="running",
        execution_mode="real",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="AI coding assistants",
            competitors=["Cursor"],
            dimensions=["pricing"],
        ),
        raw_sources=[
            RawSource(
                id="cursor-official-pricing",
                competitor="Cursor",
                dimension="pricing",
                source_type="webpage_verified",
                title="Cursor pricing",
                url="https://cursor.com/pricing",
                snippet="Cursor pricing plans are available.",
                content_hash="hash",
                confidence=0.82,
            )
        ],
    )

    issues = service._build_qa_issues(detail)

    assert any(
        issue.severity == "warn"
        and "Community triangulation was not attempted" in issue.problem
        for issue in issues
    )
```

Use the existing detail helper names in the file when they already exist; keep source and report assertions unchanged.

- [ ] **Step 2: Add failing report quality test**

Append to `backend/tests/unit/test_report_quality.py`:

```python
def test_quality_expects_community_section_when_community_evidence_exists() -> None:
    detail = _run_detail(
        run_id="run-quality-community-section",
        execution_mode="real",
        source_count=1,
        report_md=_structured_report_md(),
        metrics=RunMetrics(),
    )
    detail.raw_sources = [
        RawSource(
            id="reddit-pricing",
            competitor="Cursor",
            dimension="pricing",
            source_type="reddit_thread",
            title="Cursor pricing reddit",
            url="https://reddit.com/r/cursor/comments/pricing",
            snippet="Cursor Pro is $20 per month.",
            content_hash="hash",
            confidence=0.62,
            metadata={"community_evidence": True},
        )
    ]

    comparison = compare_run_quality(detail, baseline=detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert "community_evidence_section_score" in metrics
    assert metrics["community_evidence_section_score"].target_value == 0.0
    assert round(sum(metric.weight for metric in comparison.metrics), 6) == 1.0
```

- [ ] **Step 3: Run QA and quality tests and verify they fail**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -k "community_public_signal or typed_community_sources_as_unverified or community_observation_written_as_official or community_triangulation_was_not_attempted" -q
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_report_quality.py -k "community_section_when_community_evidence_exists" -q
```

Expected: FAIL because QA and report quality do not know community source semantics.

- [ ] **Step 4: Add community source constants to QA**

In `backend/packages/agents/qa/logic.py`, add:

```python
COMMUNITY_PUBLIC_SOURCE_TYPES = {
    "community_forum",
    "reddit_thread",
    "github_discussion",
    "github_issue",
    "review_site",
    "developer_blog",
}
```

Update `PERSONA_PUBLIC_SOURCE_TYPES` to:

```python
PERSONA_PUBLIC_SOURCE_TYPES = {"webpage_verified", *COMMUNITY_PUBLIC_SOURCE_TYPES}
```

- [ ] **Step 5: Exempt typed community sources from generic unverified-source blocking**

In `_build_collect_qa_issues()` in `backend/packages/agents/qa/logic.py`, update `unverified_sources` to exclude community evidence sources:

```python
        unverified_sources = [
            source
            for source in detail.raw_sources
            if source.dimension in detail.plan.dimensions
            and source.source_type != "webpage_verified"
            and source.source_type not in COMMUNITY_PUBLIC_SOURCE_TYPES
            and not source.metadata.get("community_evidence")
            and source.url is not None
        ]
```

- [ ] **Step 6: Add writer QA official/community guard**

In `backend/packages/agents/qa/logic.py`, add this helper near writer QA issue helpers:

```python
    def _build_community_official_commitment_issues(
        self,
        detail: RunDetail,
    ) -> list[QCIssue]:
        source_by_id = {source.id: source for source in detail.raw_sources}
        issues: list[QCIssue] = []
        for line_number, line in enumerate(detail.report_md.splitlines(), start=1):
            normalized = line.casefold()
            if "official" not in normalized:
                continue
            for source_id, source in source_by_id.items():
                if f"[source:{source_id}]" not in line:
                    continue
                if not source.metadata.get("community_evidence"):
                    continue
                if source.metadata.get("official_commitment"):
                    continue
                problem = (
                    "Report presents a community observation as official commitment; "
                    f"line {line_number} cites {source_id}."
                )
                issues.append(
                    QCIssue(
                        id=stable_prefixed_id(
                            "qc-issue",
                            "community-official-commitment",
                            source_id,
                            line_number,
                            length=16,
                        ),
                        severity="blocker",
                        detected_by="citation",
                        target_agent="writer",
                        field_path=f"report_md.line[{line_number}]",
                        problem=problem,
                        redo_scope=RedoScope(
                            kind="writer_only",
                            rationale=problem,
                        ),
                        self_found=False,
                    )
                )
        return issues
```

- [ ] **Step 7: Add QA warn for skipped community triangulation**

In `backend/packages/agents/qa/logic.py`, add:

```python
    def _build_community_attempt_issues(self, detail: RunDetail) -> list[QCIssue]:
        if detail.execution_mode != "real":
            return []
        attempted = {
            (
                str(message.payload.get("competitor") or ""),
                str(message.payload.get("dimension") or ""),
            )
            for message in detail.agent_messages
            if message.message_type == "community_search_completed"
            and isinstance(message.payload, dict)
        }
        issues: list[QCIssue] = []
        for competitor in detail.plan.competitors:
            for dimension in detail.plan.dimensions:
                has_community_source = any(
                    source.dimension == dimension
                    and self._source_matches_competitor(source, competitor)
                    and source.metadata.get("community_evidence")
                    for source in detail.raw_sources
                )
                if has_community_source or (competitor, dimension) in attempted:
                    continue
                problem = (
                    f"Community triangulation was not attempted for {competitor} / {dimension}."
                )
                issues.append(
                    QCIssue(
                        id=stable_prefixed_id(
                            "qc-issue",
                            "community-not-attempted",
                            competitor,
                            dimension,
                            length=16,
                        ),
                        severity="warn",
                        detected_by="coverage",
                        target_agent="collector",
                        target_subagent=dimension,
                        target_competitor=competitor,
                        field_path=f"agent_messages.community_search_completed[{competitor}][{dimension}]",
                        problem=problem,
                        redo_scope=RedoScope(
                            kind="collector",
                            target_subagent=dimension,
                            target_competitor=competitor,
                            rationale=problem,
                        ),
                        self_found=False,
                    )
                )
        return issues
```

In `_build_collect_qa_issues()`, after `_build_persona_evidence_strength_issues(detail, missing_dimensions)` is added and before `return issues`, add:

```python
        issues.extend(self._build_community_attempt_issues(detail))
```

In `_build_qa_issues()`, after `_build_text_quality_issues(detail)` is added, add:

```python
        issues.extend(self._build_community_official_commitment_issues(detail))
```

- [ ] **Step 8: Add community source types and metric to report quality**

In `backend/packages/business_intel/report_quality.py`, add community source types to `REAL_SOURCE_TYPES` and `REVIEW_THEME_SOURCE_TYPES`:

```python
COMMUNITY_SOURCE_TYPES = {
    "community_forum",
    "reddit_thread",
    "github_discussion",
    "github_issue",
    "review_site",
    "developer_blog",
    "snippet_only",
}
```

Update:

```python
REAL_SOURCE_TYPES = {
    "official",
    "official_docs",
    "official_pricing",
    "official_site",
    "official_api",
    "pricing_page",
    "review_site",
    "trust_center",
    "news",
    "web_search_result",
    "webpage_verified",
    *COMMUNITY_SOURCE_TYPES,
}
```

Update:

```python
REVIEW_THEME_SOURCE_TYPES = {
    "review_site",
    *USER_RESEARCH_SOURCE_TYPES,
    *COMMUNITY_SOURCE_TYPES,
}
```

Add a score helper near other section score helpers:

```python
def _community_evidence_section_score(detail: RunDetail) -> float:
    if not any(source.metadata.get("community_evidence") for source in detail.raw_sources):
        return 1.0
    section = _find_section_before_support(
        detail.report_md,
        _report_label_aliases("community_evidence_triangulation"),
    )
    if section is not None and _section_has_substantive_body(section):
        return 1.0
    body = repair_mojibake_text(detail.report_md).casefold()
    if "community observation" in body and "official" in body:
        return 0.75
    return 0.0
```

Register it in the quality metric values where other section metrics are computed:

```python
        "community_evidence_section_score": _community_evidence_section_score(detail),
```

Register it in `normalized`:

```python
        "community_evidence_section_score": values["community_evidence_section_score"],
```

Register it in `_metric_specs()`:

```python
        ("source_coverage_rate", 0.06, "higher_is_better"),
        ("verified_source_rate", 0.06, "higher_is_better"),
        ("community_evidence_section_score", 0.02, "higher_is_better"),
```

This replaces the existing `source_coverage_rate` and `verified_source_rate` weights of `0.07`, keeping total metric weight at `1.00`.

Add it to the `report_quality_signal` section gate:

```python
        and values["community_evidence_section_score"] >= 1.0
```

- [ ] **Step 9: Run QA and quality tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -k "community_public_signal or typed_community_sources_as_unverified or community_observation_written_as_official or community_triangulation_was_not_attempted" -q
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_report_quality.py -k "community_section_when_community_evidence_exists" -q
```

Expected: PASS.

- [ ] **Step 10: Run ruff**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\agents\qa\logic.py backend\packages\business_intel\report_quality.py backend\tests\unit\test_run_service.py backend\tests\unit\test_report_quality.py
```

Expected: `All checks passed!`

- [ ] **Step 11: Commit Task 8**

Run:

```powershell
git add backend/packages/agents/qa/logic.py backend/packages/business_intel/report_quality.py backend/tests/unit/test_run_service.py backend/tests/unit/test_report_quality.py
git commit -m "feat: guard community evidence semantics"
```

---

### Task 9: Regression Verification For Cursor Pricing Community Evidence

**Files:**
- Modify: `backend/tests/unit/test_run_service.py`
- Modify: `backend/tests/unit/test_report_quality.py`

- [ ] **Step 1: Add end-to-end unit regression for Cursor pricing community evidence**

Append to `backend/tests/unit/test_run_service.py`:

```python
@pytest.mark.asyncio
async def test_cursor_pricing_uses_community_caveat_when_official_pricing_is_thin() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            web_search_provider="perplexity",
            collector_target_verified_sources_per_branch=1,
            collector_community_enabled=True,
            collector_community_queries_per_branch=3,
            collector_community_target_sources_per_branch=3,
            writer_timeout_seconds=5,
        )
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistants",
            competitors=["Cursor"],
            dimensions=["pricing", "review"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="cursor-official-pricing",
            competitor="Cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.com/pricing",
            snippet="Cursor provides pricing plans, but fetched content did not expose all usage limits.",
            content_hash="official-hash",
            confidence=0.82,
        ),
        RawSource(
            id="cursor-reddit-pricing",
            competitor="Cursor",
            dimension="pricing",
            source_type="reddit_thread",
            title="Cursor Pro pricing thread",
            url="https://reddit.com/r/cursor/comments/pricing",
            snippet="Users report Cursor Pro is $20 per month and discuss usage limits.",
            content_hash="reddit-hash",
            confidence=0.68,
            metadata={"community_evidence": True, "community_source_type": "reddit_thread"},
        ),
        RawSource(
            id="cursor-forum-pricing",
            competitor="Cursor",
            dimension="pricing",
            source_type="community_forum",
            title="Cursor pricing forum",
            url="https://forum.cursor.com/t/pricing",
            snippet="Forum users report Cursor Pro price is $20 per month and ask about quotas.",
            content_hash="forum-hash",
            confidence=0.72,
            metadata={"community_evidence": True, "community_source_type": "community_forum"},
        ),
    ]

    service._annotate_community_claim_clusters(record.detail, ["pricing"])
    service._merge_structured_knowledge_slice(
        record.detail,
        competitor="Cursor",
        dimension="pricing",
        findings=[
            "Official pricing content is thin on usage limits. [source:cursor-official-pricing]",
            "Community sources report Cursor Pro is $20 per month. [source:cursor-reddit-pricing]",
            "Forum users discuss quota concerns. [source:cursor-forum-pricing]",
        ],
    )
    record.detail.report_md = service._harden_report_markdown(
        record.detail,
        (
            "# Report\n\n"
            "## Community Evidence Triangulation\n"
            "Official pricing evidence is incomplete on usage limits. Multiple community "
            "sources consistently report Cursor Pro at $20 per month, so this is a "
            "community observation rather than an official commitment. "
            "[source:cursor-reddit-pricing] [source:cursor-forum-pricing]\n"
        ),
    )

    assert "community observation rather than an official commitment" in record.detail.report_md
    assert "unknown" not in record.detail.report_md.casefold()
    assert record.detail.raw_sources[1].metadata["community_claim_clusters"][0]["label"] in {
        "community_observed",
        "community_triangulated",
    }
```

- [ ] **Step 2: Add report quality passing case for community section**

Append to `backend/tests/unit/test_report_quality.py`:

```python
def test_quality_accepts_labeled_community_observation_section() -> None:
    detail = _run_detail(
        run_id="run-quality-community-labeled",
        execution_mode="real",
        source_count=1,
        report_md=(
            _structured_report_md()
            + "\n\n## Community Evidence Triangulation\n"
            + "Community observation: users report Cursor Pro at $20 per month, "
            + "but this is not an official commitment. [source:cursor-reddit-pricing]\n"
        ),
        metrics=RunMetrics(),
    )
    detail.raw_sources = [
        RawSource(
            id="cursor-reddit-pricing",
            competitor="Cursor",
            dimension="pricing",
            source_type="reddit_thread",
            title="Cursor pricing reddit",
            url="https://reddit.com/r/cursor/comments/pricing",
            snippet="Cursor Pro is $20 per month.",
            content_hash="hash",
            confidence=0.62,
            metadata={"community_evidence": True},
        )
    ]

    comparison = compare_run_quality(detail, baseline=detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["community_evidence_section_score"].target_value == 1.0
```

- [ ] **Step 3: Run regression tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_cursor_pricing_uses_community_caveat_when_official_pricing_is_thin backend\tests\unit\test_report_quality.py::test_quality_accepts_labeled_community_observation_section -q
```

Expected: PASS.

- [ ] **Step 4: Run the community-focused test suite**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_community_query_planner.py backend\tests\unit\test_community_source_classifier.py backend\tests\unit\test_community_claims.py -q
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -k "community" -q
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_report_quality.py -k "community" -q
```

Expected: PASS.

- [ ] **Step 5: Run ruff for all touched files**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\community backend\packages\research\models.py backend\packages\research\discovery\constants.py backend\packages\research\discovery\providers.py backend\packages\research\capture\policy.py backend\packages\config\settings.py backend\packages\schema\messages.py backend\packages\i18n\language.py backend\packages\agents\collectors\logic.py backend\packages\agents\collectors\skill_tools.py backend\packages\agents\analysts\logic.py backend\packages\agents\comparator\logic.py backend\packages\agents\writer\logic.py backend\packages\agents\qa\logic.py backend\packages\business_intel\report_quality.py backend\tests\unit\test_community_query_planner.py backend\tests\unit\test_community_source_classifier.py backend\tests\unit\test_community_claims.py backend\tests\unit\test_run_service.py backend\tests\unit\test_report_quality.py
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit Task 9**

Run:

```powershell
git add backend/tests/unit/test_run_service.py backend/tests/unit/test_report_quality.py
git commit -m "test: cover community evidence regression"
```

---

## Final Verification

- [ ] **Step 1: Run all community and affected regression tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_community_query_planner.py backend\tests\unit\test_community_source_classifier.py backend\tests\unit\test_community_claims.py backend\tests\unit\test_review_theme_summary.py -q
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -k "community or review_summary or writer_source_digest or persona_strength" -q
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_report_quality.py -k "community or review or user_research" -q
```

Expected: PASS.

- [ ] **Step 2: Run ruff for all changed Python files**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\community backend\packages\research\models.py backend\packages\research\discovery\constants.py backend\packages\research\discovery\providers.py backend\packages\research\capture\policy.py backend\packages\config\settings.py backend\packages\schema\messages.py backend\packages\i18n\language.py backend\packages\agents\collectors\logic.py backend\packages\agents\collectors\skill_tools.py backend\packages\agents\analysts\logic.py backend\packages\agents\comparator\logic.py backend\packages\agents\writer\logic.py backend\packages\agents\qa\logic.py backend\packages\business_intel\report_quality.py backend\tests\unit\test_community_query_planner.py backend\tests\unit\test_community_source_classifier.py backend\tests\unit\test_community_claims.py backend\tests\unit\test_run_service.py backend\tests\unit\test_report_quality.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Inspect git status**

Run:

```powershell
git status --short
```

Expected: only unrelated existing untracked artifacts remain, or a clean tracked-file status after the final commits.
