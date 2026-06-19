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
