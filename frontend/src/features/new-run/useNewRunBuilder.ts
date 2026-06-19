import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createRun, getRuntime, getWorkspaceQuotaDecision, listScenarioPacks, listSkills } from "../../api/client";
import type {
  RunCreateRequest,
  RuntimeConfig,
  ScenarioPack,
  SkillSpec,
  WorkspaceQuotaDecision,
} from "../../api/types";
import {
  coreDimensions,
  isDimensionLocked,
  lockedDimensionsForScenario,
  mergeDimensions,
  scenarioCompetitorPreset,
  starterPresetDimensions,
  type StarterPreset,
} from "./dimensions";
import {
  defaultCompetitors,
  defaultWorkspaceId,
  dynamicScenarioId,
  type CompetitorMode,
  type ExecutionMode,
  type LayerSelection,
  type OutputLanguage,
} from "./types";

export function useNewRunBuilder() {
  const navigate = useNavigate();
  const [topic, setTopic] = useState("AI research assistant competitive analysis");
  const [competitorMode, setCompetitorMode] = useState<CompetitorMode>("auto");
  const [competitors, setCompetitors] = useState("");
  const [skills, setSkills] = useState<SkillSpec[]>([]);
  const [scenarioPacks, setScenarioPacks] = useState<ScenarioPack[]>([]);
  const [selectedLayer, setSelectedLayer] = useState<LayerSelection>("auto");
  const [scenarioId, setScenarioId] = useState("");
  const [runtime, setRuntime] = useState<RuntimeConfig | null>(null);
  const [quotaDecision, setQuotaDecision] = useState<WorkspaceQuotaDecision | null>(null);
  const [selected, setSelected] = useState<string[]>(coreDimensions);
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("demo");
  const [outputLanguage, setOutputLanguage] = useState<OutputLanguage>("zh-CN");
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

  function updateSelectedLayer(layer: LayerSelection) {
    setSelectedLayer(layer);
    if (
      scenarioId &&
      !dynamicScenarioSelected &&
      scenarioPacks.find((pack) => pack.id === scenarioId)?.competitor_layer !== layer
    ) {
      setScenarioId("");
    }
  }

  function updateManualMode() {
    setCompetitorMode("manual");
    setCompetitors((current) => current || defaultCompetitors);
  }

  function toggleDimension(skillName: string) {
    const locked = isDimensionLocked(skillName, lockedDimensions);
    if (locked) return;
    setSelected((current) =>
      current.includes(skillName)
        ? current.filter((item) => item !== skillName)
        : [...current, skillName],
    );
  }

  function toggleHitl(enabled: boolean) {
    setHitlEnabled(enabled);
    if (enabled) {
      setAutoRedoWarn(false);
    }
  }

  async function submitRun() {
    if (runBlockedByQuota) {
      setError(quotaDecision?.reason ?? "Workspace quota blocks new runs.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const payload: RunCreateRequest = {
        idempotency_key: newRunIdempotencyKey(),
        topic,
        competitors: competitorList,
        dimensions: selected,
        competitor_layer: selectedLayer === "auto" ? null : selectedLayer,
        scenario_id: scenarioId || null,
        execution_mode: executionMode,
        output_language: outputLanguage,
        auto_redo_warn_enabled: autoRedoWarn,
        hitl_enabled: hitlEnabled,
      };
      const run = await createRun(payload);
      navigate(`/runs/${"id" in run ? run.id : run.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create run");
    } finally {
      setSubmitting(false);
    }
  }

  return {
    applyScenario,
    applyStarterPreset,
    autoRedoWarn,
    competitorList,
    competitorMode,
    competitors,
    dynamicScenarioSelected,
    error,
    executionMode,
    hitlEnabled,
    isSubmitting,
    lockedDimensions,
    outputLanguage,
    quotaDecision,
    runBlockedByQuota,
    runtime,
    scenarioId,
    scenarioPacks,
    selected,
    selectedLayer,
    selectedScenario,
    setAutoRedoWarn,
    setCompetitorMode,
    setCompetitors,
    setError,
    setExecutionMode,
    setOutputLanguage,
    setScenarioId,
    setSelected,
    setTopic,
    skills,
    submitRun,
    toggleDimension,
    toggleHitl,
    topic,
    updateManualMode,
    updateSelectedLayer,
  };
}

function newRunIdempotencyKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `ui-run:${crypto.randomUUID()}`;
  }
  return `ui-run:${Date.now().toString(36)}:${Math.random().toString(36).slice(2)}`;
}
