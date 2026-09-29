import { useEffect, useMemo, useRef, useState } from "react";
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
} from "./dimensions";
import {
  defaultWorkspaceId,
  depthBudgets,
  dynamicScenarioId,
  type CollaborationMode,
  type CompetitorMode,
  type ExecutionMode,
  type LayerSelection,
  type OutputLanguage,
  type ResearchDepth,
} from "./types";
import { useTranslation } from "../../stores/i18n";

export function useNewRunBuilder() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [topic, setTopic] = useState("");
  const [targetName, setTargetName] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [productCategory, setProductCategory] = useState("");
  const [productAudience, setProductAudience] = useState("");
  const [productUseCases, setProductUseCases] = useState("");
  const [productMarket, setProductMarket] = useState("");
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
  const [researchDepth, setResearchDepth] = useState<ResearchDepth>("standard");
  const [collaborationMode, setCollaborationMode] = useState<CollaborationMode>("ai");
  const [decisionQuestion, setDecisionQuestion] = useState("");
  const [primaryJob, setPrimaryJob] = useState("");
  const [successMetric, setSuccessMetric] = useState("");
  const [autoRedoWarn, setAutoRedoWarn] = useState(false);
  const [isSubmitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitInFlightRef = useRef(false);

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
    const seen = new Set<string>();
    return competitors
      .split(",")
      .map((item) => item.trim())
      .filter((item) => {
        const key = item.toLocaleLowerCase();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      });
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
  const manualScopeError = useMemo(() => {
    if (competitorMode !== "manual" || !targetName.trim()) return null;
    const budget = depthBudgets[researchDepth];
    if (competitorList.length > budget.competitors) {
      return t("newRun.competitorLimit")
        .replace("{requested}", String(competitorList.length))
        .replace("{limit}", String(budget.competitors));
    }
    const scopeKey = (name: string) => name.toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
    const includesTarget = competitorList.some((name) => scopeKey(name) === scopeKey(targetName));
    const slices = Math.max(1, competitorList.length + (includesTarget ? 0 : 1)) * selected.length;
    if (slices > budget.slices) {
      return t("newRun.sliceLimit")
        .replace("{requested}", String(slices))
        .replace("{limit}", String(budget.slices));
    }
    return null;
  }, [competitorList, competitorMode, researchDepth, selected.length, targetName, t]);

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

  function updateCollaborationMode(mode: CollaborationMode) {
    setCollaborationMode(mode);
    if (mode === "assisted") {
      setAutoRedoWarn(false);
    }
  }

  async function submitRun() {
    if (submitInFlightRef.current) {
      return;
    }
    if (runBlockedByQuota) {
      setError(quotaDecision?.reason ?? "Workspace quota blocks new runs.");
      return;
    }
    if (manualScopeError) {
      setError(manualScopeError);
      return;
    }
    const productName = targetName.trim();
    if (productName.length < 2) {
      setError("请填写目标产品名称（至少两个字符）。");
      return;
    }
    if (competitorMode === "auto" && !runtime?.has_web_search_key) {
      setError("自动发现竞品需要搜索服务；也可以改为手动填写竞品。");
      return;
    }
    const officialUrl = targetUrl.trim();
    if (officialUrl) {
      try {
        if (!["http:", "https:"].includes(new URL(officialUrl).protocol)) throw new Error();
      } catch {
        setError("产品官网需要完整的 http 或 https 地址。");
        return;
      }
    }
    submitInFlightRef.current = true;
    setSubmitting(true);
    setError(null);
    try {
      const payload: RunCreateRequest = {
        idempotency_key: newRunIdempotencyKey(),
        topic: topic.trim() || `研究${productName}的同类竞品和替代方案`,
        target_product: {
          name: productName,
          official_url: officialUrl || null,
          category: productCategory.trim(),
          audience: productAudience.trim(),
          use_cases: [...new Set(productUseCases.split(/[,，\n]/).map(item => item.trim()).filter(Boolean))].slice(0, 8),
          market: productMarket.trim(),
        },
        competitors: competitorList,
        dimensions: selected,
        competitor_layer: selectedLayer === "auto" ? null : selectedLayer,
        scenario_id: scenarioId || null,
        execution_mode: executionMode,
        output_language: outputLanguage,
        research_depth: researchDepth,
        collaboration_mode: collaborationMode,
        decision_brief: {
          decision_question: decisionQuestion.trim(),
          primary_job: primaryJob.trim(),
          success_metric: successMetric.trim(),
        },
        auto_redo_warn_enabled: collaborationMode === "ai" && autoRedoWarn,
        hitl_enabled: collaborationMode === "assisted",
      };
      const run = await createRun(payload);
      navigate(`/runs/${"id" in run ? run.id : run.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create run");
    } finally {
      submitInFlightRef.current = false;
      setSubmitting(false);
    }
  }

  return {
    applyScenario,
    autoRedoWarn,
    collaborationMode,
    competitorList,
    competitorMode,
    competitors,
    dynamicScenarioSelected,
    error,
    executionMode,
    decisionQuestion,
    primaryJob,
    successMetric,
    isSubmitting,
    lockedDimensions,
    manualScopeError,
    outputLanguage,
    researchDepth,
    quotaDecision,
    runBlockedByQuota,
    runtime,
    scenarioId,
    scenarioPacks,
    selected,
    selectedLayer,
    selectedScenario,
    setAutoRedoWarn,
    setCollaborationMode: updateCollaborationMode,
    setCompetitorMode,
    setCompetitors,
    setError,
    setExecutionMode,
    setDecisionQuestion,
    setPrimaryJob,
    setSuccessMetric,
    setOutputLanguage,
    setResearchDepth,
    setScenarioId,
    setSelected,
    setTopic,
    targetName,
    setTargetName,
    targetUrl,
    setTargetUrl,
    productCategory,
    setProductCategory,
    productAudience,
    setProductAudience,
    productUseCases,
    setProductUseCases,
    productMarket,
    setProductMarket,
    skills,
    submitRun,
    toggleDimension,
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
