from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from packages.schema.models import SkillSpec
from packages.schema.rag import RetrievalRecord

CompetitorLayer = Literal["L1", "L2", "L3", "unknown"]
EvidenceQualityLabel = Literal["unreviewed", "accepted", "rejected", "stale"]
EnterpriseRole = Literal["owner", "admin", "analyst", "reviewer", "viewer"]
SourceRobotsStatus = Literal["unknown", "allowed", "blocked", "error"]
SourceTrustLevel = Literal["official", "verified", "community", "synthetic", "unknown"]
ArtifactType = Literal["web_snapshot", "pdf", "screenshot", "raw_text", "report_export", "other"]
ArtifactStorageBackend = Literal["local", "external", "s3", "oss"]
NotificationChannel = Literal["in_app", "email", "webhook", "feishu"]
NotificationSeverity = Literal["info", "success", "warning", "critical"]
NotificationStatus = Literal["queued", "sent", "failed", "read"]
NotificationType = Literal[
    "scheduled_scan_summary",
    "scheduled_scan_failure",
    "approval_request",
    "approval_timeout",
    "anomaly_alert",
    "quota_warning",
    "release_gate_blocked",
]
QuotaEnforcementMode = Literal["monitor", "block"]
WorkspaceUsageStatus = Literal["ok", "warn", "exceeded"]
ClaimValidationStatus = Literal["supported", "weak", "unsupported", "blocked"]
QualityAgentStatus = Literal["pass", "warn", "blocker"]
MemoryFeedbackType = Literal["correction", "preference", "approval", "rejection", "note"]
MemoryTargetType = Literal["report", "claim", "evidence", "dimension", "competitor", "project"]
MemoryCandidateKind = Literal[
    "preferred_dimension",
    "source_preference",
    "writing_preference",
    "risk_preference",
    "correction",
]
MemoryCandidateStatus = Literal["candidate", "confirmed", "rejected", "archived"]
SourceSnapshotKind = Literal["webpage", "pdf", "screenshot", "interview", "survey", "manual"]
ToolRegistryCategory = Literal[
    "collection",
    "retrieval",
    "analysis",
    "governance",
    "storage",
    "workflow",
]
ToolSideEffect = Literal["none", "network_read", "network_write", "file_write", "database_write"]
ToolPolicyTag = Literal[
    "requires_robots",
    "requires_redaction",
    "requires_trace",
    "tenant_scoped",
    "cost_metered",
    "human_review_recommended",
]
ToolRegistryStatus = Literal["enabled", "guarded", "disabled"]
ModelProviderKind = Literal["primary", "backup", "demo"]
ModelRouteStatus = Literal["selected", "fallback", "blocked"]
KnowledgeGraphNodeType = Literal[
    "project",
    "competitor",
    "dimension",
    "claim",
    "evidence",
    "source",
    "report",
]


class WorkspaceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    is_active: bool = True
    monthly_run_quota: int = Field(default=1000, ge=0)
    monthly_token_quota: int = Field(default=2_000_000, ge=0)
    monthly_cost_quota_usd: float = Field(default=100.0, ge=0.0)
    quota_enforcement: QuotaEnforcementMode = "block"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UserRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    display_name: str
    role: EnterpriseRole = "owner"
    status: Literal["active", "disabled"] = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkspaceMemberRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    user_id: str
    role: EnterpriseRole = "viewer"
    status: Literal["active", "disabled"] = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkspaceQuotaUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthly_run_quota: int | None = Field(default=None, ge=0)
    monthly_token_quota: int | None = Field(default=None, ge=0)
    monthly_cost_quota_usd: float | None = Field(default=None, ge=0.0)
    quota_enforcement: QuotaEnforcementMode | None = None


class WorkspaceUsageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    period_start: datetime
    period_end: datetime
    run_count: int = Field(default=0, ge=0)
    completed_run_count: int = Field(default=0, ge=0)
    failed_run_count: int = Field(default=0, ge=0)
    interrupted_run_count: int = Field(default=0, ge=0)
    input_tokens_estimate: int = Field(default=0, ge=0)
    output_tokens_estimate: int = Field(default=0, ge=0)
    total_tokens_estimate: int = Field(default=0, ge=0)
    cost_estimate_usd: float = Field(default=0.0, ge=0.0)
    monthly_run_quota: int = Field(default=1000, ge=0)
    monthly_token_quota: int = Field(default=2_000_000, ge=0)
    monthly_cost_quota_usd: float = Field(default=100.0, ge=0.0)
    run_usage_ratio: float = Field(default=0.0, ge=0.0)
    token_usage_ratio: float = Field(default=0.0, ge=0.0)
    cost_usage_ratio: float = Field(default=0.0, ge=0.0)
    status: WorkspaceUsageStatus = "ok"
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class WorkspaceQuotaDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    allowed: bool
    status: WorkspaceUsageStatus
    enforcement: QuotaEnforcementMode
    reason: str = ""
    usage: WorkspaceUsageSummary


class NotificationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    project_id: str | None = None
    notification_type: NotificationType
    channel: NotificationChannel = "in_app"
    severity: NotificationSeverity = "info"
    status: NotificationStatus = "queued"
    title: str
    body: str = ""
    resource_type: str | None = None
    resource_id: str | None = None
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    sent_at: datetime | None = None
    read_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    name: str
    topic: str
    topic_normalized: str
    competitor_layer: CompetitorLayer = "unknown"
    competitor_set_hash: str = ""
    scenario_id: str | None = None
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CompetitorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    name: str
    normalized_name: str
    layer: CompetitorLayer = "unknown"
    homepage_url: HttpUrl | None = None
    aliases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectCompetitorLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    competitor_id: str
    role: Literal["target", "baseline", "adjacent"] = "target"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    project_id: str
    run_id: str | None = None
    raw_source_id: str
    competitor_id: str
    dimension: str
    source_type: str
    title: str
    url: HttpUrl | None = None
    canonical_url: str = ""
    snippet: str = ""
    content_hash: str
    reliability_score: float = Field(default=0.0, ge=0.0, le=1.0)
    freshness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    quality_label: EvidenceQualityLabel = "unreviewed"
    first_seen_run_id: str | None = None
    last_seen_run_id: str | None = None
    seen_count: int = Field(default=1, ge=1)
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceRegistryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    domain: str
    source_type: str
    display_name: str
    homepage_url: HttpUrl | None = None
    trust_level: SourceTrustLevel = "unknown"
    robots_status: SourceRobotsStatus = "unknown"
    is_active: bool = True
    first_seen_run_id: str | None = None
    last_seen_run_id: str | None = None
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    seen_count: int = Field(default=1, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceEmbeddingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    project_id: str
    evidence_id: str
    embedding_model: str
    embedding_dimensions: int = Field(default=384, ge=1)
    embedding_hash: str
    embedding_text: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceSearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: EvidenceRecord
    score: float = Field(ge=-1.0, le=1.0)
    embedding_model: str


class ArtifactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    project_id: str
    evidence_id: str | None = None
    run_id: str | None = None
    artifact_type: ArtifactType = "raw_text"
    filename: str
    media_type: str = "application/octet-stream"
    storage_backend: ArtifactStorageBackend = "local"
    uri: str
    byte_size: int = Field(ge=0)
    content_hash: str
    source_url: HttpUrl | None = None
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    project_id: str
    evidence_id: str | None = None
    run_id: str | None = None
    artifact_type: ArtifactType = "raw_text"
    filename: str = Field(min_length=1, max_length=180)
    media_type: str = Field(default="text/plain", min_length=1, max_length=120)
    content_text: str | None = None
    content_base64: str | None = None
    external_uri: str | None = None
    source_url: HttpUrl | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactCreateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: ArtifactRecord


class SourceSnapshotCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    project_id: str
    evidence_id: str | None = None
    run_id: str | None = None
    snapshot_kind: SourceSnapshotKind = "webpage"
    artifact_type: ArtifactType = "web_snapshot"
    filename: str = Field(min_length=1, max_length=180)
    media_type: str = Field(default="text/plain", min_length=1, max_length=120)
    content_text: str | None = None
    content_base64: str | None = None
    external_uri: str | None = None
    source_url: HttpUrl | None = None
    source_type: str = "webpage_verified"
    display_name: str = ""
    trust_level: SourceTrustLevel = "verified"
    robots_status: SourceRobotsStatus = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceSnapshotResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: ArtifactRecord
    source: SourceRegistryRecord
    evidence_id: str | None = None
    snapshot_quality_score: int = Field(ge=0, le=100)
    warnings: list[str] = Field(default_factory=list)


class ToolRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    category: ToolRegistryCategory
    description: str
    input_schema: str
    output_schema: str
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    side_effects: list[ToolSideEffect] = Field(default_factory=list)
    policy_tags: list[ToolPolicyTag] = Field(default_factory=list)
    status: ToolRegistryStatus = "enabled"
    allowed_in_real_mode: bool = True
    reason: str = ""


class ToolRegistryReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: str = "2026-06-h10-tool-registry"
    entries: list[ToolRegistryEntry]
    total_count: int = Field(ge=0)
    guarded_count: int = Field(ge=0)
    disabled_count: int = Field(ge=0)
    side_effect_tool_count: int = Field(ge=0)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ModelRouteCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_kind: ModelProviderKind
    provider_name: str
    model_name: str
    configured: bool
    quality_score: int = Field(ge=0, le=100)
    cost_score: int = Field(ge=0, le=100)
    compliance_score: int = Field(ge=0, le=100)
    supports_tool_calling: bool = True
    supports_json_schema: bool = True
    reason: str = ""


class ModelRouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ModelRouteStatus
    selected: ModelRouteCandidate | None = None
    fallback: ModelRouteCandidate | None = None
    candidates: list[ModelRouteCandidate]
    blocked_reasons: list[str] = Field(default_factory=list)
    routing_policy_version: str = "2026-06-h10-model-router"
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class KnowledgeGraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    node_type: KnowledgeGraphNodeType
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeGraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_id: str
    target_id: str
    relation: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeGraphReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    project_id: str
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    nodes: list[KnowledgeGraphNode]
    edges: list[KnowledgeGraphEdge]
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class EvidenceReindexResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indexed_count: int = Field(ge=0)


class ClaimRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    project_id: str
    run_id: str | None = None
    competitor_id: str
    claim_type: str
    claim_text: str
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: Literal["proposed", "accepted", "disputed", "rejected", "deprecated"] = "proposed"
    created_by_agent: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReportVersionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    project_id: str
    run_id: str | None = None
    parent_version_id: str | None = None
    version_number: int = Field(ge=1)
    topic_normalized: str
    competitor_layer: CompetitorLayer = "unknown"
    competitor_set_hash: str
    status: Literal["draft", "in_review", "approved", "published", "archived"] = "draft"
    report_md: str = ""
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    quality_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: datetime | None = None


class UserFeedbackCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_type: MemoryFeedbackType = "note"
    target_type: MemoryTargetType = "project"
    target_id: str = Field(default="", max_length=200)
    run_id: str | None = None
    report_version_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    tags: list[str] = Field(default_factory=list)
    auto_confirm: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserFeedbackRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    project_id: str
    user_id: str
    feedback_type: MemoryFeedbackType = "note"
    target_type: MemoryTargetType = "project"
    target_id: str = ""
    run_id: str | None = None
    report_version_id: str | None = None
    message: str
    tags: list[str] = Field(default_factory=list)
    redaction_counts: dict[str, int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    project_id: str
    kind: MemoryCandidateKind
    status: MemoryCandidateStatus = "candidate"
    statement: str
    weight: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_feedback_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    match_score: float = Field(default=0.0, ge=0.0, le=1.0)
    used_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryRecallContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    project_id: str
    query: str = ""
    query_tags: list[str] = Field(default_factory=list)
    candidates: list[MemoryCandidate] = Field(default_factory=list)
    prompt_context: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryFeedbackIngestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: UserFeedbackRecord
    candidates: list[MemoryCandidate] = Field(default_factory=list)
    recall: MemoryRecallContext


class MemoryStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str | None = None
    project_id: str | None = None
    feedback_count: int = Field(default=0, ge=0)
    candidate_count: int = Field(default=0, ge=0)
    confirmed_candidate_count: int = Field(default=0, ge=0)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ReportDiffLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["unchanged", "added", "removed"]
    text: str


class ReportVersionDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: ReportVersionRecord | None = None
    target_version: ReportVersionRecord
    added_lines: int = 0
    removed_lines: int = 0
    unchanged_lines: int = 0
    lines: list[ReportDiffLine] = Field(default_factory=list)


class EnterpriseRunProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    project_id: str
    run_id: str
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    claim_records: list[ClaimRecord] = Field(default_factory=list)
    report_version: ReportVersionRecord


class CompetitorLayerAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer: Literal["L1", "L2", "L3"]
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str
    signals: list[str] = Field(default_factory=list)


class ScenarioPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    competitor_layer: Literal["L1", "L2", "L3"]
    required_dimensions: list[str] = Field(default_factory=list)
    optional_dimensions: list[str] = Field(default_factory=list)
    analyst_questions: list[str] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)
    qa_rule_ids: list[str] = Field(default_factory=list)
    is_dynamic: bool = False


class BusinessQARule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    severity: Literal["info", "warn", "blocker"]
    applies_to_layers: list[Literal["L1", "L2", "L3"]] = Field(default_factory=list)
    required_dimensions: list[str] = Field(default_factory=list)
    min_sources_per_competitor: int = Field(default=1, ge=0)
    require_verified_source: bool = True
    rationale: str = ""


class BusinessIntelPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    competitor_layer: CompetitorLayerAssessment
    scenario_pack: ScenarioPack
    requested_dimensions: list[str] = Field(default_factory=list)
    recommended_dimensions: list[str] = Field(default_factory=list)
    qa_rules: list[BusinessQARule] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BusinessQAFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    rule_id: str
    rule_name: str
    severity: Literal["info", "warn", "blocker"]
    competitor_id: str | None = None
    competitor_name: str | None = None
    dimension: str | None = None
    message: str
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    recommendation: str = ""


class BusinessQAEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    scenario_id: str
    competitor_layer: Literal["L1", "L2", "L3"]
    total_rules: int = 0
    passed_rules: int = 0
    finding_count: int = 0
    blocker_count: int = 0
    warn_count: int = 0
    info_count: int = 0
    findings: list[BusinessQAFinding] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class BusinessRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    priority: Literal["critical", "high", "medium", "low"]
    title: str
    detail: str
    action_type: Literal[
        "collect_evidence",
        "review_evidence",
        "fix_claim",
        "expand_competitors",
        "approve_report",
    ]
    target_type: Literal["project", "competitor", "dimension", "evidence", "claim"] = "project"
    target_id: str | None = None


class CompetitorDimensionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    score: int = Field(ge=0, le=100)
    evidence_count: int = Field(ge=0)
    claim_count: int = Field(ge=0)
    average_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str


class CompetitorScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor_id: str
    competitor_name: str
    total_score: int = Field(ge=0, le=100)
    evidence_score: int = Field(ge=0, le=100)
    claim_score: int = Field(ge=0, le=100)
    coverage_score: int = Field(ge=0, le=100)
    risk_penalty: int = Field(default=0, ge=0, le=100)
    rank: int = Field(ge=1)
    dimension_scores: list[CompetitorDimensionScore] = Field(default_factory=list)
    recommendation: str


class CompetitorScoreReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    top_competitor_id: str | None = None
    scores: list[CompetitorScore] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectReadinessScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    score: int = Field(ge=0, le=100)
    risk_level: Literal["ready", "watch", "at_risk", "blocked"]
    evidence_score: int = Field(ge=0, le=100)
    claim_score: int = Field(ge=0, le=100)
    coverage_score: int = Field(ge=0, le=100)
    qa_score: int = Field(ge=0, le=100)
    summary: str
    recommendations: list[BusinessRecommendation] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ReportReleaseGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version_id: str
    workspace_id: str
    project_id: str
    allowed: bool
    status: Literal["pass", "blocked"]
    readiness: ProjectReadinessScore
    qa_evaluation: BusinessQAEvaluation
    issue_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    warn_count: int = Field(ge=0)
    issues: list[BusinessQAFinding] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ClaimValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    claim_id: str
    severity: Literal["warn", "blocker"]
    issue_type: Literal[
        "missing_evidence",
        "stale_or_rejected_evidence",
        "weak_text_support",
        "low_evidence_quality",
        "single_source_support",
        "low_self_consistency",
        "low_confidence",
    ]
    message: str
    evidence_ids: list[str] = Field(default_factory=list)


class ClaimValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    status: ClaimValidationStatus
    support_score: int = Field(ge=0, le=100)
    text_support_score: int = Field(default=0, ge=0, le=100)
    evidence_quality_score: int = Field(default=0, ge=0, le=100)
    triangulation_score: int = Field(default=0, ge=0, le=100)
    self_consistency_score: int = Field(default=0, ge=0, le=100)
    consistency_votes: dict[str, int] = Field(default_factory=dict)
    usable_evidence_ids: list[str] = Field(default_factory=list)
    issue_ids: list[str] = Field(default_factory=list)


class ClaimValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    total_claims: int = Field(default=0, ge=0)
    supported_count: int = Field(default=0, ge=0)
    weak_count: int = Field(default=0, ge=0)
    unsupported_count: int = Field(default=0, ge=0)
    blocked_count: int = Field(default=0, ge=0)
    issue_count: int = Field(default=0, ge=0)
    blocker_count: int = Field(default=0, ge=0)
    warn_count: int = Field(default=0, ge=0)
    self_consistency_score: int = Field(default=0, ge=0, le=100)
    low_consistency_count: int = Field(default=0, ge=0)
    results: list[ClaimValidationResult] = Field(default_factory=list)
    issues: list[ClaimValidationIssue] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class QualityAgentMatrixEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: str
    framework: str
    status: QualityAgentStatus
    score: int = Field(ge=0, le=100)
    blocker_count: int = Field(default=0, ge=0)
    warn_count: int = Field(default=0, ge=0)
    finding_count: int = Field(default=0, ge=0)
    summary: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class QualityAgentMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    status: QualityAgentStatus
    overall_score: int = Field(ge=0, le=100)
    entries: list[QualityAgentMatrixEntry] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class EvidenceGapItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    severity: Literal["critical", "high", "medium", "low"]
    gap_type: Literal[
        "missing_dimension_coverage",
        "missing_verified_source",
        "stale_or_rejected_evidence",
        "claim_without_usable_evidence",
        "landscape_breadth",
    ]
    competitor_id: str | None = None
    competitor_name: str | None = None
    dimension: str | None = None
    source_type_required: str | None = None
    message: str
    recommended_query: str = ""
    retrieval_query: str = ""
    retrieval_candidate_ids: list[str] = Field(default_factory=list)
    retrieval_records: list[RetrievalRecord] = Field(default_factory=list)
    retrieval_grounded_context: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)


class SchemaEvolutionSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: Literal["pending_review"] = "pending_review"
    dimension: str
    normalized_dimension: str
    reason: str
    source_gap_ids: list[str] = Field(default_factory=list)
    proposed_skill: SkillSpec
    created_by: str = "evidence_gap_agent"
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class EvidenceGapReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    scenario_id: str
    gap_count: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    gaps: list[EvidenceGapItem] = Field(default_factory=list)
    schema_suggestions: list[SchemaEvolutionSuggestion] = Field(default_factory=list)
    agent_name: str = "pydantic_ai_evidence_gap"
    framework: str = "pydantic-ai"
    pydantic_ai_available: bool = False
    pydantic_ai_execution_mode: str = "deterministic_handler"
    pydantic_ai_model_backed_requested: bool = False
    pydantic_ai_model_backed_fallback: bool = False
    pydantic_ai_runtime_agent_created: bool = False
    pydantic_ai_runtime_result_type: str | None = None
    pydantic_ai_model_name: str | None = None
    typed_contract_enforced: bool = True
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class EvidenceGapFillResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    workspace_id: str
    source_report_version_id: str | None = None
    updated_report_version_id: str | None = None
    gap_count: int = Field(ge=0)
    before_gap_count: int = Field(default=0, ge=0)
    after_gap_count: int = Field(default=0, ge=0)
    gap_closure_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    filled_gap_count: int = Field(ge=0)
    added_evidence_count: int = Field(ge=0)
    online_collected_evidence_count: int = Field(default=0, ge=0)
    online_failure_count: int = Field(default=0, ge=0)
    gap_fill_chain_closed: bool = False
    candidate_evidence_ids: list[str] = Field(default_factory=list)
    filled_gap_ids: list[str] = Field(default_factory=list)
    remaining_gap_ids: list[str] = Field(default_factory=list)
    report: EvidenceGapReport
    updated_report_version: ReportVersionRecord | None = None
    source_release_gate: ReportReleaseGate | None = None
    updated_release_gate: ReportReleaseGate | None = None
    release_gate_improved: bool = False
    release_gate_blocker_delta: int = 0
    release_gate_warn_delta: int = 0
    readiness_score_delta: int = 0
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class RedTeamFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    severity: Literal["critical", "high", "medium", "low"]
    finding_type: Literal[
        "unsupported_claim",
        "weak_evidence",
        "stale_or_rejected_evidence",
        "competitive_bias",
        "homepage_phantom",
        "report_risk",
    ]
    competitor_id: str | None = None
    competitor_name: str | None = None
    dimension: str | None = None
    message: str
    recommendation: str
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)


class RedTeamReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    finding_count: int = 0
    high_severity_count: int = 0
    findings: list[RedTeamFinding] = Field(default_factory=list)
    agent_name: str = "pydantic_ai_red_team"
    framework: str = "pydantic-ai"
    pydantic_ai_available: bool = False
    pydantic_ai_execution_mode: str = "deterministic_handler"
    pydantic_ai_model_backed_requested: bool = False
    pydantic_ai_model_backed_fallback: bool = False
    pydantic_ai_runtime_agent_created: bool = False
    pydantic_ai_runtime_result_type: str | None = None
    pydantic_ai_model_name: str | None = None
    typed_contract_enforced: bool = True
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class EvidenceQualityUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality_label: EvidenceQualityLabel
    note: str = Field(default="", max_length=500)


class EvidenceQualityUpdateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: EvidenceRecord


class AuditLogRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    actor_type: Literal["user", "agent", "workflow", "system"]
    actor_id: str | None = None
    action: str
    resource_type: str
    resource_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
