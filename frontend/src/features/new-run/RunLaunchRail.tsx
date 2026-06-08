import { KeyRound, Play, RefreshCw } from "lucide-react";
import type {
  RuntimeConfig,
  ScenarioPack,
  WorkspaceQuotaDecision,
} from "../../api/types";
import { RuntimeLine } from "./RuntimeLine";
import type { CompetitorMode, ExecutionMode, LayerSelection } from "./types";

interface RunLaunchRailProps {
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
  setExecutionMode: (mode: ExecutionMode) => void;
  toggleHitl: (enabled: boolean) => void;
}

export function RunLaunchRail({
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
  setExecutionMode,
  toggleHitl,
}: RunLaunchRailProps) {
  return (
    <aside className="run-builder-rail">
      <section className="panel launch-panel">
        <div className="panel-heading-row">
          <h2>Execution</h2>
          <span className={executionMode === "real" ? "flow-status running" : "flow-status"}>
            {executionMode}
          </span>
        </div>
        <div className="segmented-control" role="radiogroup" aria-label="Execution mode">
          <button
            className={executionMode === "demo" ? "active" : ""}
            type="button"
            onClick={() => setExecutionMode("demo")}
          >
            Demo
          </button>
          <button
            className={executionMode === "real" ? "active" : ""}
            type="button"
            onClick={() => setExecutionMode("real")}
          >
            <KeyRound size={15} aria-hidden />
            Real API
          </button>
        </div>

        {runtime ? (
          <div className="runtime-lines">
            <RuntimeLine
              ok={
                (runtime.has_ark_api_key && runtime.has_ark_model) ||
                (runtime.has_backup_llm_api_key && runtime.has_backup_llm_model)
              }
            >
              {runtime.has_ark_api_key && runtime.has_ark_model
                ? `Primary LLM ${runtime.ark_model}`
                : runtime.has_backup_llm_api_key && runtime.has_backup_llm_model
                  ? `Backup LLM ${runtime.backup_llm_model}`
                  : "LLM credentials missing"}
            </RuntimeLine>
            <RuntimeLine ok={runtime.has_web_search_key}>
              {runtime.has_web_search_key
                ? `${runtime.web_search_provider} search enabled`
                : "Search credentials missing"}
            </RuntimeLine>
            <RuntimeLine ok={runtime.auto_redo_enabled}>
              {runtime.auto_redo_enabled ? "Scoped redo enabled" : "Scoped redo disabled"}
            </RuntimeLine>
            <RuntimeLine ok={runtime.hitl_demo_ready}>
              {runtime.hitl_demo_ready
                ? `HITL ${runtime.hitl_review_checkpoints.join(", ")}`
                : runtime.hitl_ready_reason}
            </RuntimeLine>
            <RuntimeLine ok={runtime.pydantic_ai_model_backed_ready}>
              {runtime.pydantic_ai_model_backed_ready
                ? `Pydantic-AI ${runtime.pydantic_ai_model_name}`
                : runtime.pydantic_ai_model_backed_reason}
            </RuntimeLine>
            <RuntimeLine ok={runtime.temporal_cutover_ready}>
              {runtime.temporal_cutover_ready
                ? `Temporal ${runtime.temporal_task_queue}`
                : runtime.temporal_cutover_reason}
            </RuntimeLine>
            {quotaDecision ? (
              <RuntimeLine ok={quotaDecision.allowed}>
                {quotaDecision.allowed
                  ? `Quota ${quotaDecision.status}, ${quotaDecision.enforcement}`
                  : quotaDecision.reason}
              </RuntimeLine>
            ) : null}
          </div>
        ) : null}

        <label className="toggle-row">
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
        <label className="toggle-row">
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

        {error ? <p className="error-line">{error}</p> : null}

        <button
          className="primary-button full-width"
          type="submit"
          disabled={isSubmitting || selected.length === 0 || runBlockedByQuota}
        >
          {isSubmitting ? <RefreshCw size={18} aria-hidden /> : <Play size={18} aria-hidden />}
          Start run
        </button>
      </section>

      <section className="panel selection-panel">
        <h2>Run contract</h2>
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
            <dd>{competitorMode === "auto" ? "Auto discovery" : competitorList.join(", ") || "Manual"}</dd>
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
