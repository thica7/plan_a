import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { KeyRound, Play, RefreshCw } from "lucide-react";
import { createRun, getRuntime, getWorkspaceQuotaDecision, listScenarioPacks, listSkills } from "../api/client";
import type {
  CompetitorLayer,
  RuntimeConfig,
  ScenarioPack,
  SkillSpec,
  WorkspaceQuotaDecision,
} from "../api/types";

const defaultWorkspaceId = "default-workspace";
const defaultCompetitors = "Perplexity, Claude, Gemini";
const coreDimensions = ["pricing", "feature", "persona"];
type LayerSelection = "auto" | Extract<CompetitorLayer, "L1" | "L2" | "L3">;

export function NewRun() {
  const navigate = useNavigate();
  const [topic, setTopic] = useState("AI research assistant competitive analysis");
  const [competitorMode, setCompetitorMode] = useState<"auto" | "manual">("auto");
  const [competitors, setCompetitors] = useState("");
  const [skills, setSkills] = useState<SkillSpec[]>([]);
  const [scenarioPacks, setScenarioPacks] = useState<ScenarioPack[]>([]);
  const [selectedLayer, setSelectedLayer] = useState<LayerSelection>("auto");
  const [scenarioId, setScenarioId] = useState("");
  const [runtime, setRuntime] = useState<RuntimeConfig | null>(null);
  const [quotaDecision, setQuotaDecision] = useState<WorkspaceQuotaDecision | null>(null);
  const [selected, setSelected] = useState<string[]>(coreDimensions);
  const [executionMode, setExecutionMode] = useState<"demo" | "real">("demo");
  const [autoRedoWarn, setAutoRedoWarn] = useState(false);
  const [hitlEnabled, setHitlEnabled] = useState(false);
  const [isSubmitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getRuntime()
      .then((config) => {
        setRuntime(config);
        setExecutionMode(config.default_execution_mode);
        setAutoRedoWarn(config.auto_redo_warn_enabled);
        setHitlEnabled(config.hitl_enabled);
      })
      .catch((err: Error) => setError(err.message));

    listSkills()
      .then((items) => {
        setSkills(items);
        if (items.length > 0) {
          const preferred = coreDimensions.filter((name) =>
            items.some((skill) => skill.name === name),
          );
          setSelected(preferred.length > 0 ? preferred : items.slice(0, 3).map((skill) => skill.name));
        }
      })
      .catch((err: Error) => setError(err.message));

    listScenarioPacks()
      .then(setScenarioPacks)
      .catch((err: Error) => setError(err.message));

    getWorkspaceQuotaDecision(defaultWorkspaceId)
      .then(setQuotaDecision)
      .catch(() => setQuotaDecision(null));
  }, []);

  const competitorList = useMemo(
    () => {
      if (competitorMode === "auto") {
        return [];
      }
      return competitors
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    },
    [competitorMode, competitors],
  );
  const selectedScenario = useMemo(
    () => scenarioPacks.find((pack) => pack.id === scenarioId) ?? null,
    [scenarioId, scenarioPacks],
  );
  const runBlockedByQuota = quotaDecision?.allowed === false;

  function applyScenario(pack: ScenarioPack | null) {
    if (!pack) {
      setScenarioId("");
      return;
    }
    setScenarioId(pack.id);
    setSelectedLayer(pack.competitor_layer);
    setSelected((current) => mergeDimensions(current, pack.required_dimensions, pack.optional_dimensions));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (runBlockedByQuota) {
      setError(quotaDecision?.reason ?? "Workspace quota blocks new runs.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const run = await createRun({
        idempotency_key: newRunIdempotencyKey(),
        topic,
        competitors: competitorList,
        dimensions: selected,
        competitor_layer: selectedLayer === "auto" ? null : selectedLayer,
        scenario_id: scenarioId || null,
        execution_mode: executionMode,
        auto_redo_warn_enabled: autoRedoWarn,
        hitl_enabled: hitlEnabled,
      });
      navigate(`/runs/${"id" in run ? run.id : run.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create run");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="work-surface">
      <header className="page-header">
        <div>
          <h1>New analysis run</h1>
          <p>Start with the schema-first contract, then watch the agent graph progress in real time.</p>
        </div>
      </header>

      <form className="run-form" onSubmit={handleSubmit}>
        <label>
          Topic
          <input value={topic} onChange={(event) => setTopic(event.target.value)} />
        </label>

        <fieldset>
          <legend>Competitors</legend>
          <div className="segmented-control" role="radiogroup" aria-label="Competitor mode">
            <button
              className={competitorMode === "auto" ? "active" : ""}
              type="button"
              onClick={() => setCompetitorMode("auto")}
            >
              Auto-discover
            </button>
            <button
              className={competitorMode === "manual" ? "active" : ""}
              type="button"
              onClick={() => {
                setCompetitorMode("manual");
                setCompetitors((current) => current || defaultCompetitors);
              }}
            >
              Manual
            </button>
          </div>
          {competitorMode === "manual" ? (
            <textarea
              aria-label="Competitors"
              value={competitors}
              onChange={(event) => setCompetitors(event.target.value)}
              rows={3}
            />
          ) : (
            <p className="scope-note">
              Planner will search the market and select direct competitors before collecting evidence.
            </p>
          )}
        </fieldset>

        <fieldset>
          <legend>Competitive lens</legend>
          <div className="segmented-control" role="radiogroup" aria-label="Competitive layer">
            {(["auto", "L1", "L2", "L3"] as LayerSelection[]).map((layer) => (
              <button
                className={selectedLayer === layer ? "active" : ""}
                key={layer}
                type="button"
                onClick={() => {
                  setSelectedLayer(layer);
                  if (
                    scenarioId
                    && scenarioPacks.find((pack) => pack.id === scenarioId)?.competitor_layer !== layer
                  ) {
                    setScenarioId("");
                  }
                }}
              >
                {layer === "auto" ? "Auto" : layer}
              </button>
            ))}
          </div>
          <label>
            Scenario pack
            <select
              value={scenarioId}
              onChange={(event) => {
                const next = scenarioPacks.find((pack) => pack.id === event.target.value) ?? null;
                applyScenario(next);
              }}
            >
              <option value="">Auto scenario</option>
              {scenarioPacks
                .filter((pack) => selectedLayer === "auto" || pack.competitor_layer === selectedLayer)
                .map((pack) => (
                  <option key={pack.id} value={pack.id}>
                    {pack.competitor_layer} · {pack.name}
                  </option>
                ))}
            </select>
          </label>
          {selectedScenario ? (
            <div className="scenario-preview">
              <strong>{selectedScenario.name}</strong>
              <span>{selectedScenario.description}</span>
              <div>
                {[...selectedScenario.required_dimensions, ...selectedScenario.optional_dimensions].map((dimension) => (
                  <em key={dimension}>{dimension}</em>
                ))}
              </div>
            </div>
          ) : null}
        </fieldset>

        <fieldset>
          <legend>Execution</legend>
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
              <KeyRound size={16} aria-hidden />
              Real API
            </button>
          </div>
          {runtime ? (
            <div className="runtime-lines">
              <p
                className={
                  (runtime.has_ark_api_key && runtime.has_ark_model)
                  || (runtime.has_backup_llm_api_key && runtime.has_backup_llm_model)
                    ? "runtime-ok"
                    : "runtime-warn"
                }
              >
                {runtime.has_ark_api_key && runtime.has_ark_model
                  ? `Backend is ready for real calls with ${runtime.ark_model}.`
                  : runtime.has_backup_llm_api_key && runtime.has_backup_llm_model
                    ? `Backend is ready for backup LLM calls with ${runtime.backup_llm_model}.`
                    : "Real API mode needs primary ARK or BACKUP_LLM settings in backend .env."}
              </p>
              <p className={runtime.has_web_search_key ? "runtime-ok" : "runtime-warn"}>
                {runtime.has_web_search_key
                  ? `${runtime.web_search_provider} web_search is enabled.`
                  : "web_search needs PPLX_API_KEY or PERPLEXITY_API_KEY in backend .env."}
              </p>
              <p className={runtime.auto_redo_enabled ? "runtime-ok" : "runtime-warn"}>
                {runtime.auto_redo_enabled
                  ? "Automatic scoped redo is enabled."
                  : "Automatic scoped redo is disabled by backend config."}
              </p>
              <p className={runtime.hitl_demo_ready ? "runtime-ok" : "runtime-warn"}>
                {runtime.hitl_demo_ready
                  ? `HITL pauses are enabled at ${runtime.hitl_review_checkpoints.join(", ")}.`
                  : runtime.hitl_ready_reason}
              </p>
              <p className={runtime.pydantic_ai_model_backed_ready ? "runtime-ok" : "runtime-warn"}>
                {runtime.pydantic_ai_model_backed_ready
                  ? `Pydantic-AI model-backed agents use ${runtime.pydantic_ai_model_name}.`
                  : runtime.pydantic_ai_model_backed_reason}
              </p>
              <p className={runtime.temporal_cutover_ready ? "runtime-ok" : "runtime-warn"}>
                {runtime.temporal_cutover_ready
                  ? `Run entry is 100% routed through Temporal on ${runtime.temporal_task_queue}.`
                  : runtime.temporal_cutover_reason}
              </p>
              {quotaDecision ? (
                <p className={quotaDecision.allowed ? "runtime-ok" : "runtime-warn"}>
                  {quotaDecision.allowed
                    ? `Workspace quota allows new runs (${quotaDecision.status}, ${quotaDecision.enforcement}).`
                    : quotaDecision.reason}
                </p>
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
              <em>When enabled, warn-level QA findings can trigger automatic redo. Blockers always can.</em>
            </span>
          </label>
          <label className="toggle-row">
            <input
              checked={hitlEnabled}
              onChange={(event) => {
                const enabled = event.target.checked;
                setHitlEnabled(enabled);
                if (enabled) {
                  setAutoRedoWarn(false);
                }
              }}
              type="checkbox"
            />
            <span>
              <strong>Human review pauses</strong>
              <em>Pause this run at planner and QA checkpoints for manual resume or redo.</em>
            </span>
          </label>
        </fieldset>

        <fieldset>
          <legend>Dimensions</legend>
          <div className="skill-grid">
            {skills.map((skill) => {
              const active = selected.includes(skill.name);
              const locked = coreDimensions.includes(skill.name);
              return (
                <button
                  className={active ? "skill-tile active" : "skill-tile"}
                  key={skill.name}
                  type="button"
                  onClick={() =>
                    setSelected((current) => {
                      if (locked) return current;
                      return active ? current.filter((item) => item !== skill.name) : [...current, skill.name];
                    })
                  }
                >
                  <strong>{skill.name}</strong>
                  <span>{locked ? `${skill.description} Required schema dimension.` : skill.description}</span>
                </button>
              );
            })}
          </div>
        </fieldset>

        {error ? <p className="error-line">{error}</p> : null}

        <button
          className="primary-button"
          type="submit"
          disabled={isSubmitting || selected.length === 0 || runBlockedByQuota}
        >
          {isSubmitting ? <RefreshCw size={18} aria-hidden /> : <Play size={18} aria-hidden />}
          Start run
        </button>
      </form>
    </section>
  );
}

function mergeDimensions(current: string[], required: string[], optional: string[]) {
  const merged: string[] = [];
  const seen = new Set<string>();
  for (const dimension of [...required, ...current, ...optional]) {
    const key = dimension.trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    merged.push(dimension);
    if (merged.length >= 8) break;
  }
  return merged;
}

function newRunIdempotencyKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `ui-run:${crypto.randomUUID()}`;
  }
  return `ui-run:${Date.now().toString(36)}:${Math.random().toString(36).slice(2)}`;
}
