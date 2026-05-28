export type { components, operations, paths } from "./openapi";

export type RunStatus = "queued" | "running" | "interrupted" | "completed" | "failed";

export interface AnalysisPlan {
  topic: string;
  competitors: string[];
  dimensions: string[];
  complexity: "low" | "medium" | "high";
  competitor_layer: CompetitorLayer;
  scenario_id?: string | null;
  scenario_recommended_dimensions: string[];
  qa_rule_ids: string[];
  homepage_hints: Record<string, string>;
  created_at: string;
}

export interface RedoScope {
  kind: "writer_only" | "comparator" | "analyst" | "collector" | "full";
  target_subagent?: string | null;
  target_competitor?: string | null;
  target_competitors: string[];
  rationale: string;
}

export interface QCIssue {
  id: string;
  severity: "info" | "warn" | "blocker";
  detected_by: "citation" | "consistency" | "coverage" | "schema" | "reflector";
  target_agent: string;
  target_subagent?: string | null;
  target_competitor?: string | null;
  field_path: string;
  problem: string;
  redo_scope: RedoScope;
  self_found: boolean;
}

export interface RawSource {
  id: string;
  competitor: string;
  covered_competitors: string[];
  dimension: string;
  source_type: string;
  title: string;
  url?: string | null;
  snippet: string;
  content_hash: string;
  confidence: number;
  extracted_at: string;
}

export interface ReflectionRecord {
  iteration: number;
  coverage_gaps: string[];
  confidence_outliers: string[];
  cross_competitor_gaps: string[];
  suggested_redos: RedoScope[];
}

export interface CompetitorKB {
  competitor: string;
  slices: Record<string, string[]>;
  sources: string[];
  confidence: number;
}

export interface KnowledgeClaim {
  claim: string;
  source_ids: string[];
  confidence: number;
}

export interface FeatureNode {
  name: string;
  description: string;
  claims: KnowledgeClaim[];
  children: FeatureNode[];
}

export interface FeatureTree {
  nodes: FeatureNode[];
  summary_claims: KnowledgeClaim[];
}

export interface PricingTier {
  name: string;
  price: string;
  billing_cycle: string;
  limits: string[];
  claims: KnowledgeClaim[];
}

export interface PricingModel {
  tiers: PricingTier[];
  notes: KnowledgeClaim[];
}

export interface UserPersonaSegment {
  name: string;
  role: string;
  company_size: string;
  pain_points: string[];
  use_cases: string[];
  claims: KnowledgeClaim[];
}

export interface UserPersonaModel {
  segments: UserPersonaSegment[];
  summary_claims: KnowledgeClaim[];
}

export interface CompetitorKnowledge {
  competitor: string;
  feature_tree: FeatureTree;
  pricing_model: PricingModel;
  user_personas: UserPersonaModel;
  source_ids: string[];
  confidence: number;
}

export interface ComparisonCell {
  competitor: string;
  dimension: string;
  value: string;
  source_ids: string[];
  confidence: number;
}

export interface ComparisonMatrix {
  competitors: string[];
  dimensions: string[];
  cells: ComparisonCell[];
  winner_by_dimension: Record<string, string>;
  summary: string[];
}

export interface CompetitorCandidate {
  name: string;
  rank: number;
  selected: boolean;
  rationale: string;
  evidence_titles: string[];
  evidence_urls: string[];
  confidence: number;
}

export interface CompetitorDiscovery {
  query: string;
  candidates: CompetitorCandidate[];
  selected_competitors: string[];
  rationale: string;
  created_at: string;
}

export interface RevisionRecord {
  id: string;
  iteration: number;
  stage: string;
  target_subagent?: string | null;
  target_competitor?: string | null;
  target_competitors: string[];
  redo_scopes: RedoScope[];
  before_md: string;
  after_md: string;
  issue_ids: string[];
  qa_issue_ids_before: string[];
  issue_count_before: number;
  issue_count_after: number;
  convergence_ratio: number;
  created_at: string;
}

export interface TraceSpan {
  id: string;
  kind: "llm" | "search" | "fetch" | "tool";
  agent: string;
  subagent?: string | null;
  name: string;
  status: "ok" | "error";
  model?: string | null;
  provider?: string | null;
  duration_ms: number;
  input_chars: number;
  output_chars: number;
  input_tokens_estimate: number;
  output_tokens_estimate: number;
  cost_estimate_usd: number;
  input_preview: string;
  output_preview: string;
  full_input: string;
  full_output: string;
  metadata: Record<string, string | number | boolean | null>;
  created_at: string;
}

export interface AgentMessage {
  id: string;
  run_id: string;
  from_agent: string;
  to_agent: string;
  message_type: string;
  payload_schema: string;
  payload: Record<string, unknown>;
  source_message_ids: string[];
  trace_span_ids: string[];
  status: "queued" | "consumed";
  consumed_by?: string | null;
  consumed_at?: string | null;
  consumer_context_id?: string | null;
  created_at: string;
}

export interface ToolCallMessage {
  id: string;
  run_id: string;
  agent: string;
  subagent?: string | null;
  tool_name: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
  status: "ok" | "error";
  trace_span_id?: string | null;
  source_message_id?: string | null;
  created_at: string;
}

export interface RunMetrics {
  total_spans: number;
  total_duration_ms: number;
  llm_calls: number;
  search_calls: number;
  fetch_calls: number;
  input_tokens_estimate: number;
  output_tokens_estimate: number;
  cost_estimate_usd: number;
  source_coverage_rate: number;
  verified_source_rate: number;
  claim_citation_rate: number;
  schema_pass_rate: number;
  human_override_rate: number;
  acceptance_rate: number;
  qa_issue_count: number;
  revision_count: number;
}

export interface RunCreateRequest {
  workspace_id?: string;
  project_id?: string | null;
  idempotency_key?: string | null;
  topic: string;
  competitors: string[];
  dimensions: string[];
  competitor_layer?: "L1" | "L2" | "L3" | null;
  scenario_id?: string | null;
  execution_mode: "auto" | "demo" | "real";
  auto_redo_warn_enabled?: boolean;
}

export interface RunSummary {
  id: string;
  idempotency_key: string;
  workspace_id: string;
  project_id?: string | null;
  topic: string;
  status: RunStatus;
  execution_mode: "demo" | "real";
  created_at: string;
  updated_at: string;
}

export interface RunDetail extends RunSummary {
  plan: AnalysisPlan;
  max_iterations: number;
  auto_redo_warn_enabled: boolean;
  report_md: string;
  raw_sources: RawSource[];
  competitor_kbs: Record<string, CompetitorKB>;
  competitor_knowledge: Record<string, CompetitorKnowledge>;
  competitor_discovery?: CompetitorDiscovery | null;
  comparison_matrix?: ComparisonMatrix | null;
  qa_findings: QCIssue[];
  reflections: ReflectionRecord[];
  revisions: RevisionRecord[];
  agent_messages: AgentMessage[];
  tool_call_messages: ToolCallMessage[];
  trace_spans: TraceSpan[];
  metrics: RunMetrics;
  current_node?: string | null;
}

export interface WorkflowStartResponse {
  workflow_id: string;
  workflow_type: "CompetitiveIntelWorkflow";
  run_id: string;
  idempotency_key: string;
  task_queue: string;
  status: "started" | "already_started";
}

export interface SkillSpec {
  name: string;
  subagent_class: string;
  description: string;
  tools_allowlist: string[];
  query_templates: string[];
  max_turns: number;
  source_type: string;
  output: {
    prefix: string;
    confidence_default: number;
    confidence_no_url: number;
    required_dimension: string;
  };
}

export interface RuntimeConfig {
  default_execution_mode: "demo" | "real";
  demo_mode: boolean;
  has_ark_api_key: boolean;
  has_ark_model: boolean;
  ark_base_url: string;
  ark_model?: string | null;
  web_search_provider: string;
  has_web_search_key: boolean;
  auto_redo_enabled: boolean;
  auto_redo_warn_enabled: boolean;
  hitl_enabled: boolean;
  hitl_timeout_seconds: number;
}

export type CompetitorLayer = "L1" | "L2" | "L3" | "unknown";
export type EvidenceQualityLabel = "unreviewed" | "accepted" | "rejected" | "stale";

export interface CompetitorLayerAssessment {
  layer: "L1" | "L2" | "L3";
  confidence: number;
  rationale: string;
  signals: string[];
}

export interface ScenarioPack {
  id: string;
  name: string;
  description: string;
  competitor_layer: "L1" | "L2" | "L3";
  required_dimensions: string[];
  optional_dimensions: string[];
  analyst_questions: string[];
  evidence_requirements: string[];
  qa_rule_ids: string[];
  is_dynamic: boolean;
}

export interface BusinessQARule {
  id: string;
  name: string;
  severity: "info" | "warn" | "blocker";
  applies_to_layers: Array<"L1" | "L2" | "L3">;
  required_dimensions: string[];
  min_sources_per_competitor: number;
  require_verified_source: boolean;
  rationale: string;
}

export interface BusinessIntelPlan {
  topic: string;
  competitor_layer: CompetitorLayerAssessment;
  scenario_pack: ScenarioPack;
  requested_dimensions: string[];
  recommended_dimensions: string[];
  qa_rules: BusinessQARule[];
  created_at: string;
}

export interface BusinessQAFinding {
  id: string;
  rule_id: string;
  rule_name: string;
  severity: "info" | "warn" | "blocker";
  competitor_id?: string | null;
  competitor_name?: string | null;
  dimension?: string | null;
  message: string;
  evidence_ids: string[];
  claim_ids: string[];
  recommendation: string;
}

export interface BusinessQAEvaluation {
  project_id: string;
  scenario_id: string;
  competitor_layer: "L1" | "L2" | "L3";
  total_rules: number;
  passed_rules: number;
  finding_count: number;
  blocker_count: number;
  warn_count: number;
  info_count: number;
  findings: BusinessQAFinding[];
  generated_at: string;
}

export interface BusinessRecommendation {
  id: string;
  priority: "critical" | "high" | "medium" | "low";
  title: string;
  detail: string;
  action_type:
    | "collect_evidence"
    | "review_evidence"
    | "fix_claim"
    | "expand_competitors"
    | "approve_report";
  target_type: "project" | "competitor" | "dimension" | "evidence" | "claim";
  target_id?: string | null;
}

export interface CompetitorDimensionScore {
  dimension: string;
  score: number;
  evidence_count: number;
  claim_count: number;
  average_confidence: number;
  rationale: string;
}

export interface CompetitorScore {
  competitor_id: string;
  competitor_name: string;
  total_score: number;
  evidence_score: number;
  claim_score: number;
  coverage_score: number;
  risk_penalty: number;
  rank: number;
  dimension_scores: CompetitorDimensionScore[];
  recommendation: string;
}

export interface CompetitorScoreReport {
  project_id: string;
  top_competitor_id?: string | null;
  scores: CompetitorScore[];
  generated_at: string;
}

export interface ProjectReadinessScore {
  project_id: string;
  score: number;
  risk_level: "ready" | "watch" | "at_risk" | "blocked";
  evidence_score: number;
  claim_score: number;
  coverage_score: number;
  qa_score: number;
  summary: string;
  recommendations: BusinessRecommendation[];
  generated_at: string;
}

export interface EvidenceGapItem {
  id: string;
  severity: "critical" | "high" | "medium" | "low";
  gap_type:
    | "missing_dimension_coverage"
    | "missing_verified_source"
    | "stale_or_rejected_evidence"
    | "claim_without_usable_evidence"
    | "landscape_breadth";
  competitor_id?: string | null;
  competitor_name?: string | null;
  dimension?: string | null;
  source_type_required?: string | null;
  message: string;
  recommended_query: string;
  evidence_ids: string[];
  claim_ids: string[];
}

export interface EvidenceGapReport {
  project_id: string;
  scenario_id: string;
  gap_count: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  gaps: EvidenceGapItem[];
  agent_name: string;
  framework: "pydantic-ai";
  pydantic_ai_available: boolean;
  generated_at: string;
}

export interface RedTeamFinding {
  id: string;
  severity: "critical" | "high" | "medium" | "low";
  finding_type:
    | "unsupported_claim"
    | "weak_evidence"
    | "stale_or_rejected_evidence"
    | "competitive_bias"
    | "homepage_phantom"
    | "report_risk";
  competitor_id?: string | null;
  competitor_name?: string | null;
  dimension?: string | null;
  message: string;
  recommendation: string;
  evidence_ids: string[];
  claim_ids: string[];
}

export interface RedTeamReport {
  project_id: string;
  finding_count: number;
  high_severity_count: number;
  findings: RedTeamFinding[];
  agent_name: string;
  framework: "pydantic-ai";
  pydantic_ai_available: boolean;
  generated_at: string;
}

export interface WorkspaceRecord {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProjectRecord {
  id: string;
  workspace_id: string;
  name: string;
  topic: string;
  topic_normalized: string;
  competitor_layer: CompetitorLayer;
  competitor_set_hash: string;
  scenario_id?: string | null;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompetitorRecord {
  id: string;
  workspace_id: string;
  name: string;
  normalized_name: string;
  layer: CompetitorLayer;
  homepage_url?: string | null;
  aliases: string[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface EvidenceRecord {
  id: string;
  workspace_id: string;
  project_id: string;
  run_id?: string | null;
  raw_source_id: string;
  competitor_id: string;
  dimension: string;
  source_type: string;
  title: string;
  url?: string | null;
  snippet: string;
  content_hash: string;
  reliability_score: number;
  freshness_score: number;
  quality_label: EvidenceQualityLabel;
  captured_at: string;
  metadata: Record<string, unknown>;
}

export interface ClaimRecord {
  id: string;
  workspace_id: string;
  project_id: string;
  run_id?: string | null;
  competitor_id: string;
  claim_type: string;
  claim_text: string;
  evidence_ids: string[];
  confidence: number;
  status: "proposed" | "accepted" | "disputed" | "rejected" | "deprecated";
  created_by_agent?: string | null;
  created_at: string;
}

export interface ReportVersionRecord {
  id: string;
  workspace_id: string;
  project_id: string;
  run_id?: string | null;
  parent_version_id?: string | null;
  version_number: number;
  topic_normalized: string;
  competitor_layer: CompetitorLayer;
  competitor_set_hash: string;
  status: "draft" | "in_review" | "approved" | "published" | "archived";
  report_md: string;
  claim_ids: string[];
  evidence_ids: string[];
  created_at: string;
  published_at?: string | null;
}

export interface ReportDiffLine {
  kind: "unchanged" | "added" | "removed";
  text: string;
}

export interface ReportVersionDiff {
  base_version?: ReportVersionRecord | null;
  target_version: ReportVersionRecord;
  added_lines: number;
  removed_lines: number;
  unchanged_lines: number;
  lines: ReportDiffLine[];
}

export interface EnterpriseRunProjection {
  workspace_id: string;
  project_id: string;
  run_id: string;
  evidence_records: EvidenceRecord[];
  claim_records: ClaimRecord[];
  report_version: ReportVersionRecord;
}
