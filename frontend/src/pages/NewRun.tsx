import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { KeyRound, Play, RefreshCw } from "lucide-react";
import { createRun, getRuntime, listSkills } from "../api/client";
import type { RuntimeConfig, SkillSpec } from "../api/types";

const defaultCompetitors = "Perplexity, Claude, Gemini";

export function NewRun() {
  const navigate = useNavigate();
  const [topic, setTopic] = useState("AI research assistant competitive analysis");
  const [competitorMode, setCompetitorMode] = useState<"auto" | "manual">("auto");
  const [competitors, setCompetitors] = useState("");
  const [skills, setSkills] = useState<SkillSpec[]>([]);
  const [runtime, setRuntime] = useState<RuntimeConfig | null>(null);
  const [selected, setSelected] = useState<string[]>(["pricing", "feature"]);
  const [executionMode, setExecutionMode] = useState<"demo" | "real">("demo");
  const [autoRedoWarn, setAutoRedoWarn] = useState(false);
  const [isSubmitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getRuntime()
      .then((config) => {
        setRuntime(config);
        setExecutionMode(config.default_execution_mode);
        setAutoRedoWarn(config.auto_redo_warn_enabled);
      })
      .catch((err: Error) => setError(err.message));

    listSkills()
      .then((items) => {
        setSkills(items);
        if (items.length > 0) {
          const preferred = ["pricing", "feature"].filter((name) =>
            items.some((skill) => skill.name === name),
          );
          setSelected(preferred.length > 0 ? preferred : items.slice(0, 2).map((skill) => skill.name));
        }
      })
      .catch((err: Error) => setError(err.message));
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

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const run = await createRun({
        topic,
        competitors: competitorList,
        dimensions: selected,
        execution_mode: executionMode,
        auto_redo_warn_enabled: autoRedoWarn,
      });
      navigate(`/runs/${run.id}`);
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
              <p className={runtime.has_ark_api_key && runtime.has_ark_model ? "runtime-ok" : "runtime-warn"}>
                {runtime.has_ark_api_key && runtime.has_ark_model
                  ? `Backend is ready for real calls with ${runtime.ark_model}.`
                  : "Real API mode needs ARK_API_KEY and ARK_MODEL in backend .env."}
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
            </div>
          ) : null}
          <label className="toggle-row">
            <input
              checked={autoRedoWarn}
              disabled={runtime?.auto_redo_enabled === false}
              onChange={(event) => setAutoRedoWarn(event.target.checked)}
              type="checkbox"
            />
            <span>
              <strong>Auto-redo warnings</strong>
              <em>When enabled, warn-level QA findings can trigger automatic redo. Blockers always can.</em>
            </span>
          </label>
        </fieldset>

        <fieldset>
          <legend>Dimensions</legend>
          <div className="skill-grid">
            {skills.map((skill) => {
              const active = selected.includes(skill.name);
              return (
                <button
                  className={active ? "skill-tile active" : "skill-tile"}
                  key={skill.name}
                  type="button"
                  onClick={() =>
                    setSelected((current) =>
                      active
                        ? current.filter((item) => item !== skill.name)
                        : [...current, skill.name],
                    )
                  }
                >
                  <strong>{skill.name}</strong>
                  <span>{skill.description}</span>
                </button>
              );
            })}
          </div>
        </fieldset>

        {error ? <p className="error-line">{error}</p> : null}

        <button className="primary-button" type="submit" disabled={isSubmitting || selected.length === 0}>
          {isSubmitting ? <RefreshCw size={18} aria-hidden /> : <Play size={18} aria-hidden />}
          Start run
        </button>
      </form>
    </section>
  );
}
