import { FormEvent, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Gauge,
  KeyRound,
  Layers,
  ListChecks,
  Play,
  RefreshCw,
  Users,
} from "lucide-react";
import { createRun, getRuntime, getWorkspaceQuotaDecision, listScenarioPacks, listSkills } from "../api/client";
import type {
  CompetitorLayer,
  RuntimeConfig,
  ScenarioPack,
  SkillSpec,
  WorkspaceQuotaDecision,
} from "../api/types";
import {
  coreDimensions,
  isDimensionLocked,
  lockedDimensionsForScenario,
  mergeDimensions,
  scenarioCompetitorPreset,
  starterPresetDimensions,
  starterPresets,
  type StarterPreset,
} from "./newRunDimensions";

const defaultWorkspaceId = "default-workspace";
const defaultCompetitors = "Perplexity, Claude, Gemini";
const dynamicScenarioId = "dynamic_adaptive";
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

  const competitorList = useMemo(() => {
    if (competitorMode === "auto") {
      return [];
    }
    return competitors
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }, [competitorMode, competitors]);
  const selectedScenario = useMemo(
    () => scenarioPacks.find((pack) => pack.id === scenarioId) ?? null,
    [scenarioId, scenarioPacks],
  );
  const dynamicScenarioSelected = scenarioId.startsWith("dynamic");
  const lockedDimensions = useMemo(
    () => lockedDimensionsForScenario(selectedScenario),
    [selectedScenario],
  );
  const runBlockedByQuota = quotaDecision?.allowed === false;

  useEffect(() => {
    setSelected((current) => mergeDimensions(current, lockedDimensions, []));
  }, [lockedDimensions]);

  function applyScenario(pack: ScenarioPack | null) {
    if (!pack) {
      setScenarioId("");
      return;
    }
    setScenarioId(pack.id);
    setSelectedLayer(pack.competitor_layer);
    setSelected((current) => mergeDimensions(current, pack.required_dimensions, pack.optional_dimensions));
    const seededCompetitors = scenarioCompetitorPreset(pack);
    if (seededCompetitors) {
      setCompetitorMode("manual");
      setCompetitors(seededCompetitors);
    }
  }

  function applyStarterPreset(preset: StarterPreset) {
    setTopic(preset.topic);
    setSelectedLayer(preset.competitorLayer);
    setScenarioId(preset.scenarioId);
    setCompetitorMode("manual");
    setCompetitors(preset.competitors.join(", "));
    setSelected(starterPresetDimensions(preset));
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
    <section className="work-surface new-run-page">
      <header className="page-header page-header-split">
        <div>
          <h1>New analysis run</h1>
          <p>Configure the market scope, research lens, execution mode, and quality controls before launch.</p>
        </div>
        <div className="header-stat">
          <strong>{selected.length}</strong>
          <span>dimensions selected</span>
        </div>
      </header>

      <form className="run-builder" onSubmit={handleSubmit}>
        <div className="run-builder-main">
          <section className="form-section">
            <SectionHeading
              icon={<ListChecks size={17} aria-hidden />}
              index="01"
              meta="topic and starting preset"
              title="Scope"
            />
            <label className="field-block">
              Topic
              <input value={topic} onChange={(event) => setTopic(event.target.value)} />
            </label>
            <div className="preset-grid">
              {starterPresets.map((preset) => (
                <button
                  className={`preset-tile${scenarioId === preset.scenarioId ? " active" : ""}`}
                  key={preset.id}
                  type="button"
                  onClick={() => applyStarterPreset(preset)}
                >
                  <strong>{preset.name}</strong>
                  <span>{preset.competitorLayer} / {preset.scenarioId}</span>
                  <small>{preset.competitors.join(", ")}</small>
                </button>
              ))}
            </div>
          </section>

          <section className="form-section">
            <SectionHeading
              icon={<Users size={17} aria-hidden />}
              index="02"
              meta={competitorMode === "auto" ? "planner discovery" : "manual list"}
              title="Competitors"
            />
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
                Planner selects direct competitors before evidence collection.
              </p>
            )}
          </section>

          <section className="form-section">
            <SectionHeading
              icon={<Layers size={17} aria-hidden />}
              index="03"
              meta="L1 battlecard, L2 workflow, or L3 landscape"
              title="Lens"
            />
            <div className="field-grid">
              <fieldset>
                <legend>Competitive layer</legend>
                <div className="segmented-control" role="radiogroup" aria-label="Competitive layer">
                  {(["auto", "L1", "L2", "L3"] as LayerSelection[]).map((layer) => (
                    <button
                      className={selectedLayer === layer ? "active" : ""}
                      key={layer}
                      type="button"
                      onClick={() => {
                        setSelectedLayer(layer);
                        if (
                          scenarioId &&
                          !dynamicScenarioSelected &&
                          scenarioPacks.find((pack) => pack.id === scenarioId)?.competitor_layer !== layer
                        ) {
                          setScenarioId("");
                        }
                      }}
                    >
                      {layer === "auto" ? "Auto" : layer}
                    </button>
                  ))}
                </div>
              </fieldset>
              <label>
                Scenario pack
                <select
                  value={scenarioId}
                  onChange={(event) => {
                    if (event.target.value === dynamicScenarioId) {
                      setScenarioId(dynamicScenarioId);
                      return;
                    }
                    const next = scenarioPacks.find((pack) => pack.id === event.target.value) ?? null;
                    applyScenario(next);
                  }}
                >
                  <option value="">Auto scenario</option>
                  <option value={dynamicScenarioId}>Dynamic scenario</option>
                  {scenarioPacks
                    .filter((pack) => selectedLayer === "auto" || pack.competitor_layer === selectedLayer)
                    .map((pack) => (
                      <option key={pack.id} value={pack.id}>
                        {pack.competitor_layer} / {pack.name}
                      </option>
                    ))}
                </select>
              </label>
            </div>
            {selectedScenario ? (
              <div className="scenario-preview">
                <strong>{selectedScenario.name}</strong>
                <span>{selectedScenario.description}</span>
                <div>
                  {[...selectedScenario.required_dimensions, ...selectedScenario.optional_dimensions].map((dimension) => (
                    <em key={dimension}>{dimension}</em>
                  ))}
                </div>
                {selectedScenario.seed_competitors.length > 0 ? (
                  <small>{selectedScenario.seed_competitors.join(", ")}</small>
                ) : null}
              </div>
            ) : dynamicScenarioSelected ? (
              <div className="scenario-preview">
                <strong>Dynamic scenario</strong>
                <span>Generated from the selected scope and dimensions.</span>
                <div>
                  {selected.map((dimension) => (
                    <em key={dimension}>{dimension}</em>
                  ))}
                </div>
              </div>
            ) : null}
          </section>

          <section className="form-section">
            <SectionHeading
              icon={<Gauge size={17} aria-hidden />}
              index="04"
              meta={`${selected.length} active schema dimensions`}
              title="Dimensions"
            />
            <div className="skill-grid">
              {skills.map((skill) => {
                const active = selected.includes(skill.name);
                const locked = isDimensionLocked(skill.name, lockedDimensions);
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
                    <span>
                      {locked
                        ? selectedScenario
                          ? `${skill.description} Required by selected ScenarioPack.`
                          : `${skill.description} Required schema dimension.`
                        : skill.description}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        </div>

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
      </form>
    </section>
  );
}

function newRunIdempotencyKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `ui-run:${crypto.randomUUID()}`;
  }
  return `ui-run:${Date.now().toString(36)}:${Math.random().toString(36).slice(2)}`;
}

function SectionHeading({
  icon,
  index,
  meta,
  title,
}: {
  icon: ReactNode;
  index: string;
  meta: string;
  title: string;
}) {
  return (
    <div className="section-heading">
      <span>{index}</span>
      <div className="section-heading-icon">{icon}</div>
      <div>
        <h2>{title}</h2>
        <p>{meta}</p>
      </div>
    </div>
  );
}

function RuntimeLine({ children, ok }: { children: ReactNode; ok: boolean }) {
  return (
    <p className={ok ? "runtime-ok" : "runtime-warn"}>
      {ok ? <CheckCircle2 size={14} aria-hidden /> : <AlertTriangle size={14} aria-hidden />}
      <span>{children}</span>
    </p>
  );
}
