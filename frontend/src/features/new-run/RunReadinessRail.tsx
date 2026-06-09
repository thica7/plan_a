import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileCheck2,
  KeyRound,
  Play,
  RefreshCw,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import type { ReactNode } from "react";
import type {
  RuntimeConfig,
  ScenarioPack,
  WorkspaceQuotaDecision,
} from "../../api/types";
import { ActionButton } from "../../components/interaction/ActionButton";
import { RuntimeLine } from "./RuntimeLine";
import type { CompetitorMode, ExecutionMode, LayerSelection } from "./types";

interface RunReadinessRailProps {
  autoRedoWarn: boolean;
  competitorList: string[];
  competitorMode: CompetitorMode;
  dynamicScenarioSelected: boolean;
  error: string | null;
  executionMode: ExecutionMode;
  hitlEnabled: boolean;
  isSubmitting: boolean;
  quotaDecision: WorkspaceQuotaDecision | null;
  runBlockedByQuota: boolean;
  runtime: RuntimeConfig | null;
  selected: string[];
  selectedLayer: LayerSelection;
  selectedScenario: ScenarioPack | null;
  setAutoRedoWarn: (enabled: boolean) => void;
  toggleHitl: (enabled: boolean) => void;
}

export function RunReadinessRail({
  autoRedoWarn,
  competitorList,
  competitorMode,
  dynamicScenarioSelected,
  error,
  executionMode,
  hitlEnabled,
  isSubmitting,
  quotaDecision,
  runBlockedByQuota,
  runtime,
  selected,
  selectedLayer,
  selectedScenario,
  setAutoRedoWarn,
  toggleHitl,
}: RunReadinessRailProps) {
  const llmReady = Boolean(
    (runtime?.has_ark_api_key && runtime.has_ark_model) ||
      (runtime?.has_backup_llm_api_key && runtime.has_backup_llm_model),
  );
  const searchReady = Boolean(runtime?.has_web_search_key);
  const temporalReady = Boolean(runtime?.temporal_cutover_ready);
  const pydanticReady = Boolean(runtime?.pydantic_ai_model_backed_ready);
  const complianceReady = Boolean(runtime?.compliance_redaction_enabled);
  const readyCount = [
    llmReady,
    searchReady,
    temporalReady,
    complianceReady,
    quotaDecision?.allowed !== false,
    selected.length > 0,
  ].filter(Boolean).length;
  const readinessStatus = runBlockedByQuota ? "Blocked" : readyCount >= 5 ? "Ready" : "Review";
  const competitorSummary =
    competitorMode === "auto"
      ? "Auto-discover"
      : competitorList.length > 0
        ? `${competitorList.length} selected`
        : "Manual";

  return (
    <aside className="run-builder-rail">
      <section className="panel run-readiness-panel">
        <div className="run-readiness-header">
          <div>
            <h2>Run Readiness</h2>
            <p>Runtime, source policy, review gates, and launch state.</p>
          </div>
          <span className={runBlockedByQuota ? "flow-status failed" : "flow-status pass"}>
            <CheckCircle2 size={14} aria-hidden />
            {readinessStatus}
          </span>
        </div>

        <div className="readiness-checklist" aria-label="Run readiness checklist">
          <ReadinessItem icon={<ShieldCheck size={15} />} ok={Boolean(quotaDecision?.allowed ?? true)} title="Workspace">
            {quotaDecision?.allowed === false ? quotaDecision.reason : "Acme Corp"}
          </ReadinessItem>
          <ReadinessItem icon={<FileCheck2 size={15} />} ok={selected.length > 0} title="Dimensions">
            {selected.length} selected
          </ReadinessItem>
          <ReadinessItem icon={<Database size={15} />} ok={searchReady} title="Data Sources">
            {runtime?.has_web_search_key ? `${runtime.web_search_provider}, web, registry` : "Search key missing"}
          </ReadinessItem>
          <ReadinessItem icon={<KeyRound size={15} />} ok={llmReady} title="Model Route">
            {runtime?.has_ark_api_key && runtime.has_ark_model
              ? runtime.ark_model
              : runtime?.has_backup_llm_api_key && runtime.has_backup_llm_model
                ? runtime.backup_llm_model
                : "Credentials missing"}
          </ReadinessItem>
          <ReadinessItem icon={<UserCheck size={15} />} ok={hitlEnabled || autoRedoWarn} title="Quality Controls">
            {hitlEnabled ? "Human review enabled" : autoRedoWarn ? "Auto-redo enabled" : "Manual launch"}
          </ReadinessItem>
        </div>

        <div className="readiness-section">
          <header>
            <h3>Cost Estimate</h3>
            <ActionButton
              className="ghost-button"
              authenticity={{
                actionId: 'new-run.cost-details.disabled',
                kind: 'disabled',
                description: 'detailed cost breakdown not available in demo'
              }}
              disabled
              disabledReason="Detailed cost breakdown is not included in this demo build."
            >
              Details
            </ActionButton>
          </header>
          <strong className="cost-estimate">~$48.60</strong>
          <dl className="readiness-cost-list">
            <div>
              <dt>LLM Calls</dt>
              <dd>~$28.20</dd>
            </div>
            <div>
              <dt>Web Search</dt>
              <dd>~$12.40</dd>
            </div>
            <div>
              <dt>Embedding & Vector</dt>
              <dd>~$5.80</dd>
            </div>
            <div>
              <dt>Storage & Trace</dt>
              <dd>~$2.20</dd>
            </div>
          </dl>
        </div>

        <div className="readiness-section">
          <header>
            <h3>Source Policy</h3>
            <span>Strict</span>
          </header>
          <dl className="readiness-cost-list">
            <div>
              <dt>Verified Sources Only</dt>
              <dd>Required</dd>
            </div>
            <div>
              <dt>Min Domain Authority</dt>
              <dd>40</dd>
            </div>
            <div>
              <dt>Max Sources per Claim</dt>
              <dd>5</dd>
            </div>
            <div>
              <dt>Citation Required</dt>
              <dd>Yes</dd>
            </div>
          </dl>
        </div>

        <div className="readiness-section">
          <header>
            <h3>Runtime Signals</h3>
            <span>{executionMode}</span>
          </header>
          <div className="runtime-lines compact">
            <RuntimeLine ok={searchReady}>
              {searchReady ? `${runtime?.web_search_provider} search enabled` : "Search credentials missing"}
            </RuntimeLine>
            <RuntimeLine ok={temporalReady}>
              {temporalReady ? `Temporal ${runtime?.temporal_task_queue}` : runtime?.temporal_cutover_reason ?? "Temporal unavailable"}
            </RuntimeLine>
            <RuntimeLine ok={pydanticReady}>
              {pydanticReady
                ? `Pydantic-AI ${runtime?.pydantic_ai_model_name}`
                : runtime?.pydantic_ai_model_backed_reason ?? "Pydantic-AI model-backed agent disabled"}
            </RuntimeLine>
            <RuntimeLine ok={complianceReady}>
              {complianceReady ? "Compliance redaction enabled" : "Compliance redaction disabled"}
            </RuntimeLine>
          </div>
        </div>

        <div className="readiness-section">
          <header>
            <h3>HITL Checkpoints</h3>
            <span>{hitlEnabled ? "Enabled" : "Optional"}</span>
          </header>
          <label className="toggle-row compact">
            <input
              checked={autoRedoWarn}
              disabled={runtime?.auto_redo_enabled === false || hitlEnabled}
              onChange={(event) => setAutoRedoWarn(event.target.checked)}
              type="checkbox"
            />
            <span>
              <strong>Auto-redo warnings</strong>
              <em>Warn-level QA can trigger targeted redo.</em>
            </span>
          </label>
          <label className="toggle-row compact">
            <input
              checked={hitlEnabled}
              onChange={(event) => toggleHitl(event.target.checked)}
              type="checkbox"
            />
            <span>
              <strong>Human review pauses</strong>
              <em>Pause at planner and QA checkpoints.</em>
            </span>
          </label>
        </div>

        {error ? <p className="error-line">{error}</p> : null}

        <ActionButton
          className="primary-button full-width"
          type="submit"
          authenticity={{
            actionId: 'new-run.submit',
            kind: 'submit',
            description: 'submits the new run builder form'
          }}
          disabled={selected.length === 0 || runBlockedByQuota}
          disabledReason={
            runBlockedByQuota
              ? quotaDecision?.reason || 'Run blocked by workspace quota policy.'
              : selected.length === 0
                ? 'Select at least one analysis dimension before starting a run.'
                : undefined
          }
          isLoading={isSubmitting}
          loadingLabel="Starting run..."
        >
          {isSubmitting ? <RefreshCw size={18} aria-hidden /> : <Play size={18} aria-hidden />}
          Start Run
        </ActionButton>
      </section>

      <section className="panel run-contract-panel">
        <h2>Run Contract</h2>
        <dl className="contract-list">
          <div>
            <dt>Layer</dt>
            <dd>{selectedLayer}</dd>
          </div>
          <div>
            <dt>Scenario</dt>
            <dd>{selectedScenario?.name ?? (dynamicScenarioSelected ? "Dynamic" : "Auto")}</dd>
          </div>
          <div>
            <dt>Competitors</dt>
            <dd>{competitorSummary}</dd>
          </div>
        </dl>
        <div className="contract-chips">
          {selected.map((dimension) => (
            <span key={dimension}>{dimension}</span>
          ))}
        </div>
      </section>
    </aside>
  );
}

function ReadinessItem({
  children,
  icon,
  ok,
  title,
}: {
  children: ReactNode;
  icon: ReactNode;
  ok: boolean;
  title: string;
}) {
  return (
    <div className={ok ? "readiness-item ok" : "readiness-item warn"}>
      <span>{icon}</span>
      <div>
        <strong>{title}</strong>
        <em>{children}</em>
      </div>
      {ok ? <CheckCircle2 size={14} aria-hidden /> : <AlertTriangle size={14} aria-hidden />}
    </div>
  );
}
