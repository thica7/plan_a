export type { components, operations, paths } from "./openapi";

export type RunStatus =
  | "queued"
  | "running"
  | "interrupted"
  | "completed"
  | "completed_with_blockers"
  | "failed";

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
  trace_id: string;
  otel_span_id: string;
  parent_span_id?: string | null;
  traceparent: string;
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

export interface OtelSpanExport {
  trace_id: string;
  span_id: string;
  parent_span_id?: string | null;
  name: string;
  kind: string;
  status_code: "OK" | "ERROR";
  start_time_unix_nano: number;
  end_time_unix_nano: number;
  attributes: Record<string, string | number | boolean | null>;
}

export interface OtelTraceExport {
  run_id: string;
  exporter: "otlp-json-compatible";
  trace_id: string;
  resource: Record<string, string>;
  spans: OtelSpanExport[];
  generated_at: string;
}

export interface TraceObservabilityIssue {
  severity: "info" | "warn" | "blocker";
  field: string;
  message: string;
  span_id?: string | null;
}

export interface TraceObservabilityReport {
  run_id: string;
  status: "pass" | "warn" | "fail";
  span_count: number;
  trace_id_coverage: number;
  traceparent_coverage: number;
  otel_span_id_coverage: number;
  parent_link_count: number;
  errored_span_count: number;
  otel_export_ready: boolean;
  issues: TraceObservabilityIssue[];
  generated_at: string;
}

export interface AuditLogRecord {
  id: string;
  workspace_id: string;
  actor_type: "user" | "agent" | "workflow" | "system";
  actor_id?: string | null;
  action: string;
  resource_type: string;
  resource_id: string;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
  created_at: string;
}

export interface ComplianceFinding {
  id: string;
  severity: "info" | "warn" | "blocker";
  category: "pii" | "source" | "robots" | "policy" | "trace";
  target_type: "run" | "source" | "trace_span";
  target_id: string;
  message: string;
  recommendation: string;
}

export interface RunComplianceReport {
  run_id: string;
  status: "pass" | "warn" | "fail";
  policy: Record<string, unknown>;
  source_count: number;
  trace_span_count: number;
  redaction_count: number;
  finding_count: number;
  blocker_count: number;
  warn_count: number;
  findings: ComplianceFinding[];
  generated_at: string;
}

export type DecisionEventType =
  | "agent.started"
  | "agent.finished"
  | "tool.called"
  | "rag.retrieved"
  | "memory.recalled"
  | "memory.feedback_captured"
  | "hitl.reviewed"
  | "self_consistency.sampled"
  | "claim.validated"
  | "qa.blocked"
  | "redo.routed"
  | "benchmark.scored"
  | "report.ready";

export interface DecisionReplayEvent {
  id: string;
  run_id: string;
  event_type: DecisionEventType;
  agent?: string | null;
  subagent?: string | null;
  message: string;
  source_event_id?: number | null;
  related_span_ids: string[];
  evidence_ids: string[];
  claim_ids: string[];
  payload: Record<string, unknown>;
  created_at: string;
}

export interface DecisionReplayReport {
  run_id: string;
  status: string;
  event_count: number;
  blocker_count: number;
  warn_count: number;
  replay_coverage_score: number;
  event_type_counts: Record<string, number>;
  events: DecisionReplayEvent[];
  generated_at: string;
}

export type EvalOpsStatus = "pass" | "warn" | "fail";
export type EvalJudgeMode = "heuristic" | "llm";

export interface EvalOpsMetric {
  name: string;
  value: number;
  target: number;
  unit: string;
  status: EvalOpsStatus;
  summary: string;
}

export interface EvalOpsCaseResult {
  case_id: string;
  name: string;
  status: EvalOpsStatus;
  score: number;
  target_run_id?: string | null;
  baseline_run_id?: string | null;
  summary: string;
}

export interface EvalOpsQualityChainStep {
  step: "real_collection" | "real_llm" | "report_quality";
  label: string;
  total_count: number;
  passed_count: number;
  failed_count: number;
  pass_rate: number;
  failed_run_ids: string[];
  summary: string;
}

export interface EvalOpsReport {
  run_count: number;
  evaluated_run_ids: string[];
  baseline_run_id?: string | null;
  real_run_count: number;
  demo_run_count: number;
  real_run_ratio: number;
  real_quality_chain_rate: number;
  real_quality_chain_failed_run_ids: string[];
  quality_chain_steps: EvalOpsQualityChainStep[];
  average_delta_score?: number | null;
  regressed_run_count: number;
  judge_mode: EvalJudgeMode;
  judge_avg_score: number;
  llm_judge_avg_score?: number | null;
  judge_fallback_reason: string;
  hitl_enabled_run_rate: number;
  human_correction_rate: number;
  redo_iteration_count: number;
  redo_convergence_ratio: number;
  golden_set_size: number;
  golden_set_pass_rate: number;
  report_quality_score: number;
  source_recall: number;
  compliance_pass_rate: number;
  compliance_fail_count: number;
  compliance_blocker_count: number;
  manual_baseline_hours_per_report: number;
  manual_baseline_hours: number;
  automation_runtime_hours: number;
  task_time_saved_hours: number;
  time_savings_rate: number;
  cost_per_report_usd: number;
  regression_gate_status: EvalOpsStatus;
  regression_gate_reason: string;
  metrics: EvalOpsMetric[];
  cases: EvalOpsCaseResult[];
  recommendations: string[];
  generated_at: string;
}

export type EnterpriseRole = "owner" | "admin" | "analyst" | "reviewer" | "viewer";
export type PolicyEffect = "allow" | "deny";

export interface PolicyEvaluationRequest {
  workspace_id: string;
  action: string;
  target_type?: string;
  target_id?: string | null;
}

export interface PolicyRuleMatch {
  rule_id: string;
  effect: PolicyEffect;
  message: string;
}

export interface PolicyDecision {
  allowed: boolean;
  effect: PolicyEffect;
  engine: "internal-opa-compatible" | "opa" | "cerbos";
  policy_version: string;
  subject_id: string;
  role: EnterpriseRole;
  scoped_workspace_id?: string | null;
  workspace_id: string;
  action: string;
  target_type: string;
  target_id?: string | null;
  required_role: EnterpriseRole;
  matched_rules: PolicyRuleMatch[];
  reason: string;
}

export interface ModelPolicyFinding {
  id: string;
  severity: "info" | "warn" | "blocker";
  category: "provider" | "compliance" | "cost" | "routing";
  message: string;
  recommendation: string;
}

export interface ModelPolicyReport {
  status: "pass" | "warn" | "fail";
  policy_version: string;
  default_execution_mode: string;
  primary_provider_configured: boolean;
  backup_provider_configured: boolean;
  real_execution_allowed: boolean;
  fallback_allowed: boolean;
  redaction_required: boolean;
  trace_context_required: boolean;
  max_timeout_seconds: number;
  finding_count: number;
  blocker_count: number;
  warn_count: number;
  blocking_finding_ids: string[];
  findings: ModelPolicyFinding[];
  generated_at: string;
}

export type MemoryFeedbackType = "correction" | "preference" | "approval" | "rejection" | "note";
export type MemoryTargetType =
  | "report"
  | "claim"
  | "evidence"
  | "dimension"
  | "competitor"
  | "project";
export type MemoryCandidateKind =
  | "preferred_dimension"
  | "source_preference"
  | "writing_preference"
  | "risk_preference"
  | "failure_pattern"
  | "qa_policy"
  | "correction";
export type MemoryCandidateStatus = "candidate" | "confirmed" | "rejected" | "archived";

export interface UserFeedbackCreateRequest {
  feedback_type?: MemoryFeedbackType;
  target_type?: MemoryTargetType;
  target_id?: string;
  run_id?: string | null;
  report_version_id?: string | null;
  message: string;
  tags?: string[];
  auto_confirm?: boolean;
  metadata?: Record<string, unknown>;
}

export interface UserFeedbackRecord {
  id: string;
  workspace_id: string;
  project_id: string;
  user_id: string;
  feedback_type: MemoryFeedbackType;
  target_type: MemoryTargetType;
  target_id: string;
  run_id?: string | null;
  report_version_id?: string | null;
  message: string;
  tags: string[];
  redaction_counts: Record<string, number>;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface MemoryCandidate {
  id: string;
  workspace_id: string;
  project_id: string;
  kind: MemoryCandidateKind;
  status: MemoryCandidateStatus;
  statement: string;
  weight: number;
  confidence: number;
  source_feedback_ids: string[];
  tags: string[];
  match_score: number;
  used_count: number;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface MemoryRecallContext {
  workspace_id: string;
  project_id: string;
  query: string;
  query_tags: string[];
  candidates: MemoryCandidate[];
  prompt_context: string[];
  generated_at: string;
}

export interface MemoryFeedbackIngestResult {
  feedback: UserFeedbackRecord;
  candidates: MemoryCandidate[];
  recall: MemoryRecallContext;
}

export interface MemoryStats {
  workspace_id?: string | null;
  project_id?: string | null;
  feedback_count: number;
  candidate_count: number;
  confirmed_candidate_count: number;
  generated_at: string;
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
  compliance_redaction_count: number;
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
  hitl_enabled?: boolean;
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
  hitl_enabled: boolean;
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

export interface RunQualityMetric {
  name: string;
  target_value: number;
  baseline_value?: number | null;
  delta?: number | null;
  weight: number;
  direction: "higher_is_better" | "lower_is_better";
  status: "improved" | "regressed" | "unchanged" | "baseline_missing";
}

export interface RunQualitySignalCheck {
  signal: "real_collection" | "real_llm" | "report_quality";
  label: string;
  passed: boolean;
  reason: string;
  blocking_metric_names: string[];
}

export interface RunQualityComparison {
  target_run_id: string;
  baseline_run_id?: string | null;
  target_execution_mode: "demo" | "real";
  baseline_execution_mode?: "demo" | "real" | null;
  target_score: number;
  baseline_score?: number | null;
  delta_score?: number | null;
  verdict: "pass" | "warn" | "fail";
  real_collection_signal: boolean;
  real_llm_signal: boolean;
  report_quality_signal: boolean;
  signal_checks: RunQualitySignalCheck[];
  metrics: RunQualityMetric[];
  recommendations: string[];
  generated_at: string;
}

export type ClaimValidationStatus = "supported" | "weak" | "unsupported" | "blocked";
export type ClaimValidationSampleChecker = "text_support" | "evidence_quality" | "triangulation";

export interface ClaimValidationIssue {
  id: string;
  claim_id: string;
  severity: "warn" | "blocker";
  issue_type:
    | "missing_evidence"
    | "stale_or_rejected_evidence"
    | "weak_text_support"
    | "low_evidence_quality"
    | "single_source_support"
    | "low_self_consistency"
    | "low_confidence";
  message: string;
  evidence_ids: string[];
}

export interface ClaimValidationSample {
  checker: ClaimValidationSampleChecker;
  vote: "pass" | "fail";
  score: number;
  threshold: number;
  rationale: string;
  evidence_ids: string[];
}

export interface ClaimValidationResult {
  claim_id: string;
  status: ClaimValidationStatus;
  support_score: number;
  text_support_score: number;
  evidence_quality_score: number;
  triangulation_score: number;
  self_consistency_score: number;
  consistency_votes: Record<string, number>;
  validation_samples: ClaimValidationSample[];
  usable_evidence_ids: string[];
  issue_ids: string[];
}

export interface ClaimValidationReport {
  project_id: string;
  total_claims: number;
  supported_count: number;
  weak_count: number;
  unsupported_count: number;
  blocked_count: number;
  issue_count: number;
  blocker_count: number;
  warn_count: number;
  self_consistency_score: number;
  low_consistency_count: number;
  results: ClaimValidationResult[];
  issues: ClaimValidationIssue[];
  generated_at: string;
}

export interface WorkflowStartResponse {
  workflow_id: string;
  workflow_type: "CompetitiveIntelWorkflow";
  run_id: string;
  idempotency_key: string;
  task_queue: string;
  status: "started" | "already_started";
}

export interface WorkflowStateResponse {
  workflow_id: string;
  task_queue: string;
  status:
    | "initialized"
    | "creating_run"
    | "running_langgraph"
    | "loading_projection"
    | "running"
    | "waiting"
    | "completed"
    | "partial"
    | "empty"
    | "interrupted"
    | "timed_out"
    | "failed"
    | "unknown";
  state: Record<string, unknown>;
}

export interface ScheduledScanStartRequest {
  workspace_id: string;
  schedule_id?: string;
  requested_by?: string;
  project_ids?: string[];
  dimensions?: string[];
  execution_mode?: "auto" | "demo" | "real";
  max_projects?: number;
  cron_schedule?: string | null;
}

export interface ScheduledScanStartResponse {
  workflow_id: string;
  workflow_type: "ScheduledScanWorkflow";
  workspace_id: string;
  schedule_id: string;
  task_queue: string;
  status: "started" | "already_started";
}

export interface MonitorStartRequest {
  workspace_id: string;
  project_id: string;
  monitor_id?: string;
  requested_by?: string;
  dimensions?: string[];
  execution_mode?: "auto" | "demo" | "real";
  interval_seconds?: number;
  max_cycles?: number;
}

export interface MonitorStartResponse {
  workflow_id: string;
  workflow_type: "MonitorWorkflow";
  workspace_id: string;
  project_id: string;
  monitor_id: string;
  task_queue: string;
  status: "started" | "already_started";
}

export interface ReportApprovalStartRequest {
  report_version_id: string;
  requested_by?: string;
  approver_ids?: string[];
  timeout_seconds?: number;
}

export interface ReportApprovalStartResponse {
  workflow_id: string;
  workflow_type: "ReportApprovalWorkflow";
  report_version_id: string;
  task_queue: string;
  status: "started" | "already_started";
}

export interface ReportApprovalSignalRequest {
  approver_id: string;
  note?: string;
}

export interface ReportApprovalSignalResponse {
  workflow_id: string;
  workflow_type: "ReportApprovalWorkflow";
  report_version_id: string;
  decision: "approved" | "rejected";
  status: "signaled";
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
  run_orchestration_backend: "langgraph" | "temporal";
  demo_mode: boolean;
  has_ark_api_key: boolean;
  has_ark_model: boolean;
  ark_base_url: string;
  ark_model?: string | null;
  has_backup_llm_api_key: boolean;
  has_backup_llm_model: boolean;
  backup_llm_base_url: string;
  backup_llm_model?: string | null;
  web_search_provider: string;
  has_web_search_key: boolean;
  auto_redo_enabled: boolean;
  auto_redo_warn_enabled: boolean;
  hitl_enabled: boolean;
  hitl_timeout_seconds: number;
  hitl_demo_ready: boolean;
  hitl_ready_reason: string;
  hitl_review_checkpoints: string[];
  temporal_address: string;
  temporal_namespace: string;
  temporal_task_queue: string;
  temporal_traffic_percent: number;
  temporal_cutover_ready: boolean;
  temporal_cutover_reason: string;
  compliance_redaction_enabled: boolean;
  compliance_redact_api_keys: boolean;
  compliance_redact_emails: boolean;
  compliance_redact_phones: boolean;
  compliance_allowed_domains: string[];
  compliance_blocked_domains: string[];
  compliance_require_source_urls: boolean;
  compliance_require_trace_context: boolean;
  pydantic_ai_model_backed_enabled: boolean;
  pydantic_ai_model_name?: string | null;
  pydantic_ai_available: boolean;
  pydantic_ai_model_backed_ready: boolean;
  pydantic_ai_model_backed_reason: string;
  artifact_storage_backend: string;
  artifact_storage_root: string;
  auth_policy_engine: string;
  auth_policy_external_configured: boolean;
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

export interface ReportReleaseGate {
  report_version_id: string;
  workspace_id: string;
  project_id: string;
  allowed: boolean;
  status: "pass" | "blocked";
  readiness: ProjectReadinessScore;
  qa_evaluation: BusinessQAEvaluation;
  issue_count: number;
  blocker_count: number;
  warn_count: number;
  issues: BusinessQAFinding[];
  generated_at: string;
}

export interface RetrievalRecord {
  evidence_id: string;
  chunk_id: string;
  chunk_index: number;
  score: number;
  vector_score: number;
  bm25_score: number;
  rerank_score: number;
  title: string;
  source_type: string;
  dimension: string;
  snippet: string;
  source_url: string;
  retrieval_stage: string;
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
  retrieval_query: string;
  retrieval_candidate_chunk_count: number;
  retrieval_unique_evidence_count: number;
  retrieval_dedupe_drop_count: number;
  retrieval_candidate_ids: string[];
  retrieval_records: RetrievalRecord[];
  retrieval_grounded_context: string;
  evidence_ids: string[];
  claim_ids: string[];
}

export interface SchemaEvolutionSuggestion {
  id: string;
  status: "pending_review";
  dimension: string;
  normalized_dimension: string;
  reason: string;
  source_gap_ids: string[];
  proposed_skill: SkillSpec;
  created_by: string;
  generated_at: string;
}

export type SchemaEvolutionReviewDecision = "accepted" | "rejected";

export interface SchemaEvolutionReviewRequest {
  decision: SchemaEvolutionReviewDecision;
  note?: string;
  suggestion?: SchemaEvolutionSuggestion | null;
}

export interface SchemaEvolutionReviewRecord {
  suggestion_id: string;
  decision: SchemaEvolutionReviewDecision;
  dimension: string;
  normalized_dimension: string;
  reason: string;
  source_gap_ids: string[];
  proposed_skill: SkillSpec;
  reviewed_by: string;
  reviewed_at: string;
  note: string;
}

export interface SchemaEvolutionReviewResult {
  project_id: string;
  workspace_id: string;
  review: SchemaEvolutionReviewRecord;
  project: ProjectRecord;
  accepted_schema_dimensions: Record<string, SchemaEvolutionReviewRecord>;
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
  schema_suggestions: SchemaEvolutionSuggestion[];
  agent_name: string;
  framework: "pydantic-ai";
  pydantic_ai_available: boolean;
  pydantic_ai_execution_mode: string;
  pydantic_ai_model_backed_requested: boolean;
  pydantic_ai_model_backed_fallback: boolean;
  pydantic_ai_runtime_agent_created: boolean;
  pydantic_ai_runtime_result_type?: string | null;
  pydantic_ai_model_name?: string | null;
  pydantic_ai_runtime_prompt_hash?: string | null;
  pydantic_ai_input_schema_hash?: string | null;
  pydantic_ai_output_schema_hash?: string | null;
  pydantic_ai_runtime_prompt_chars: number;
  typed_contract_enforced: boolean;
  generated_at: string;
}

export interface EvidenceGapFillDecisionEvent {
  event_type: "rag.retrieved" | "tool.called" | "report.ready";
  agent: string;
  message: string;
  gap_ids: string[];
  evidence_ids: string[];
  payload: Record<string, unknown>;
  created_at: string;
}

export interface EvidenceGapFillResult {
  project_id: string;
  workspace_id: string;
  source_report_version_id?: string | null;
  updated_report_version_id?: string | null;
  gap_count: number;
  before_gap_count: number;
  after_gap_count: number;
  gap_closure_rate: number;
  filled_gap_count: number;
  added_evidence_count: number;
  online_collected_evidence_count: number;
  online_failure_count: number;
  gap_fill_chain_closed: boolean;
  candidate_evidence_ids: string[];
  filled_gap_ids: string[];
  remaining_gap_ids: string[];
  decision_events: EvidenceGapFillDecisionEvent[];
  report: EvidenceGapReport;
  updated_report_version?: ReportVersionRecord | null;
  source_release_gate?: ReportReleaseGate | null;
  updated_release_gate?: ReportReleaseGate | null;
  release_gate_improved: boolean;
  release_gate_blocker_delta: number;
  release_gate_warn_delta: number;
  readiness_score_delta: number;
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
  pydantic_ai_execution_mode: string;
  pydantic_ai_model_backed_requested: boolean;
  pydantic_ai_model_backed_fallback: boolean;
  pydantic_ai_runtime_agent_created: boolean;
  pydantic_ai_runtime_result_type?: string | null;
  pydantic_ai_model_name?: string | null;
  pydantic_ai_runtime_prompt_hash?: string | null;
  pydantic_ai_input_schema_hash?: string | null;
  pydantic_ai_output_schema_hash?: string | null;
  pydantic_ai_runtime_prompt_chars: number;
  typed_contract_enforced: boolean;
  generated_at: string;
}

export type QualityAgentStatus = "pass" | "warn" | "blocker";

export interface QualityAgentMatrixEntry {
  agent_name: string;
  framework: string;
  status: QualityAgentStatus;
  score: number;
  blocker_count: number;
  warn_count: number;
  finding_count: number;
  summary: string;
  evidence_ids: string[];
  claim_ids: string[];
  suggested_redos: RedoScope[];
  metadata: Record<string, unknown>;
}

export interface QualityAgentMatrix {
  project_id: string;
  status: QualityAgentStatus;
  overall_score: number;
  entries: QualityAgentMatrixEntry[];
  generated_at: string;
}

export interface WorkspaceRecord {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
  monthly_run_quota: number;
  monthly_token_quota: number;
  monthly_cost_quota_usd: number;
  quota_enforcement: "monitor" | "block";
  created_at: string;
  updated_at: string;
}

export interface WorkspaceQuotaUpdateRequest {
  monthly_run_quota?: number | null;
  monthly_token_quota?: number | null;
  monthly_cost_quota_usd?: number | null;
  quota_enforcement?: "monitor" | "block" | null;
}

export interface WorkspaceUsageSummary {
  workspace_id: string;
  period_start: string;
  period_end: string;
  run_count: number;
  completed_run_count: number;
  failed_run_count: number;
  interrupted_run_count: number;
  input_tokens_estimate: number;
  output_tokens_estimate: number;
  total_tokens_estimate: number;
  cost_estimate_usd: number;
  monthly_run_quota: number;
  monthly_token_quota: number;
  monthly_cost_quota_usd: number;
  run_usage_ratio: number;
  token_usage_ratio: number;
  cost_usage_ratio: number;
  status: "ok" | "warn" | "exceeded";
  generated_at: string;
}

export interface WorkspaceQuotaDecision {
  workspace_id: string;
  allowed: boolean;
  status: "ok" | "warn" | "exceeded";
  enforcement: "monitor" | "block";
  reason: string;
  usage: WorkspaceUsageSummary;
}

export type NotificationType =
  | "scheduled_scan_summary"
  | "scheduled_scan_failure"
  | "approval_request"
  | "approval_timeout"
  | "anomaly_alert"
  | "quota_warning"
  | "release_gate_blocked";

export interface NotificationRecord {
  id: string;
  workspace_id: string;
  project_id?: string | null;
  notification_type: NotificationType;
  channel: "in_app" | "email" | "webhook" | "feishu";
  severity: "info" | "success" | "warning" | "critical";
  status: "queued" | "sent" | "failed" | "read";
  title: string;
  body: string;
  resource_type?: string | null;
  resource_id?: string | null;
  created_by?: string | null;
  created_at: string;
  sent_at?: string | null;
  read_at?: string | null;
  metadata: Record<string, unknown>;
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
  metadata: Record<string, unknown>;
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

export type ArtifactType =
  | "web_snapshot"
  | "pdf"
  | "screenshot"
  | "raw_text"
  | "report_export"
  | "other";

export interface ArtifactRecord {
  id: string;
  workspace_id: string;
  project_id: string;
  evidence_id?: string | null;
  run_id?: string | null;
  artifact_type: ArtifactType;
  filename: string;
  media_type: string;
  storage_backend: "local" | "external" | "s3" | "oss";
  uri: string;
  byte_size: number;
  content_hash: string;
  source_url?: string | null;
  created_by?: string | null;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface ArtifactCreateRequest {
  workspace_id: string;
  project_id: string;
  evidence_id?: string | null;
  run_id?: string | null;
  artifact_type?: ArtifactType;
  filename: string;
  media_type?: string;
  content_text?: string | null;
  content_base64?: string | null;
  external_uri?: string | null;
  source_url?: string | null;
  metadata?: Record<string, unknown>;
}

export interface ArtifactCreateResult {
  artifact: ArtifactRecord;
}

export interface SourceRegistryRecord {
  id: string;
  workspace_id: string;
  domain: string;
  source_type: string;
  display_name: string;
  homepage_url?: string | null;
  trust_level: "official" | "verified" | "community" | "synthetic" | "unknown";
  robots_status: "unknown" | "allowed" | "blocked" | "error";
  is_active: boolean;
  first_seen_run_id?: string | null;
  last_seen_run_id?: string | null;
  first_seen_at: string;
  last_seen_at: string;
  seen_count: number;
  metadata: Record<string, unknown>;
}

export interface SourceSnapshotCreateRequest {
  workspace_id: string;
  project_id: string;
  evidence_id?: string | null;
  run_id?: string | null;
  snapshot_kind?: "webpage" | "pdf" | "screenshot" | "interview" | "survey" | "manual";
  artifact_type?: ArtifactType;
  filename: string;
  media_type?: string;
  content_text?: string | null;
  content_base64?: string | null;
  external_uri?: string | null;
  source_url?: string | null;
  source_type?: string;
  display_name?: string;
  trust_level?: "official" | "verified" | "community" | "synthetic" | "unknown";
  robots_status?: "unknown" | "allowed" | "blocked" | "error";
  metadata?: Record<string, unknown>;
}

export interface SourceSnapshotResult {
  artifact: ArtifactRecord;
  source: SourceRegistryRecord;
  evidence_id?: string | null;
  snapshot_quality_score: number;
  warnings: string[];
}

export interface ToolRegistryEntry {
  name: string;
  category: "collection" | "retrieval" | "analysis" | "governance" | "storage" | "workflow";
  description: string;
  input_schema: string;
  output_schema: string;
  estimated_cost_usd: number;
  side_effects: ("none" | "network_read" | "network_write" | "file_write" | "database_write")[];
  policy_tags: (
    | "requires_robots"
    | "requires_redaction"
    | "requires_trace"
    | "tenant_scoped"
    | "cost_metered"
    | "human_review_recommended"
  )[];
  status: "enabled" | "guarded" | "disabled";
  allowed_in_real_mode: boolean;
  reason: string;
}

export interface ToolRegistryReport {
  policy_version: string;
  entries: ToolRegistryEntry[];
  total_count: number;
  guarded_count: number;
  disabled_count: number;
  side_effect_tool_count: number;
  generated_at: string;
}

export interface ModelRouteCandidate {
  provider_kind: "primary" | "backup" | "demo";
  provider_name: string;
  model_name: string;
  configured: boolean;
  quality_score: number;
  cost_score: number;
  compliance_score: number;
  supports_tool_calling: boolean;
  supports_json_schema: boolean;
  reason: string;
}

export interface ModelRouteDecision {
  status: "selected" | "fallback" | "blocked";
  selected?: ModelRouteCandidate | null;
  fallback?: ModelRouteCandidate | null;
  candidates: ModelRouteCandidate[];
  blocked_reasons: string[];
  routing_policy_version: string;
  generated_at: string;
}

export interface KnowledgeGraphNode {
  id: string;
  node_type: "project" | "competitor" | "dimension" | "claim" | "evidence" | "source" | "report";
  label: string;
  metadata: Record<string, unknown>;
}

export interface KnowledgeGraphEdge {
  id: string;
  source_id: string;
  target_id: string;
  relation: string;
  confidence: number;
  evidence_ids: string[];
  metadata: Record<string, unknown>;
}

export interface KnowledgeGraphReadModel {
  workspace_id: string;
  project_id: string;
  node_count: number;
  edge_count: number;
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
  generated_at: string;
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
  status: "draft" | "in_review" | "approved" | "rejected" | "published" | "archived";
  report_md: string;
  claim_ids: string[];
  evidence_ids: string[];
  quality_metadata?: Record<string, unknown>;
  created_at: string;
  published_at?: string | null;
}

export interface ManualReportRevisionRequest {
  report_md: string;
  note?: string;
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
