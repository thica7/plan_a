import type {
  AnalysisPlanTask,
  ReflectionRecord,
  RunQualityComparison,
} from "../../api/types";
import type { ReflectionItem } from "./types";

export function summarizeTaskStages(tasks: AnalysisPlanTask[]) {
  return tasks.reduce<Record<AnalysisPlanTask["stage"], number>>(
    (counts, task) => {
      counts[task.stage] += 1;
      return counts;
    },
    { collector: 0, analyst: 0, survey_interview: 0 },
  );
}

export function taskPriorityRank(priority: AnalysisPlanTask["priority"]) {
  if (priority === "high") return 3;
  if (priority === "medium") return 2;
  return 1;
}

export function taskPriorityClass(priority: AnalysisPlanTask["priority"]) {
  if (priority === "high") return "high";
  if (priority === "medium") return "medium";
  return "low";
}

export function formatQualityValue(value: number) {
  if (Number.isInteger(value)) return String(value);
  return Math.abs(value) < 1 ? value.toFixed(2) : value.toFixed(1);
}

export function metricWeightedLoss(metric: RunQualityComparison["metrics"][number]) {
  return Math.max(0, 1 - metric.target_normalized_score) * metric.weight * 100;
}

export function flattenReflection(reflection: ReflectionRecord): ReflectionItem[] {
  return [
    ...reflection.coverage_gaps.map((text, index) => ({ kind: "coverage", text, index })),
    ...reflection.confidence_outliers.map((text, index) => ({ kind: "confidence", text, index })),
    ...reflection.cross_competitor_gaps.map((text, index) => ({ kind: "cross", text, index })),
  ].filter((item) => item.text.trim());
}
