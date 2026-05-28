export type RunStatus = "queued" | "running" | "interrupted" | "completed" | "failed";

export interface AnalysisPlan {
  topic: string;
  competitors: string[];
  dimensions: string[];
  complexity: "low" | "medium" | "high";
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
  topic: string;
  competitors: string[];
  dimensions: string[];
  execution_mode: "auto" | "demo" | "real";
  auto_redo_warn_enabled?: boolean;
}

export interface RunSummary {
  id: string;
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
