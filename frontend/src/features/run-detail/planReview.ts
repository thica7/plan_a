import type { CompetitorDiscovery, CompetitorEdit } from "../../api/types";

export function normalizePlanDimension(value: string | undefined): string {
  if (!value) return "";
  return value
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ")
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export function parsePlanDimensionsInput(value: string): string[] {
  const seen = new Set<string>();
  const dimensions: string[] = [];
  for (const item of value.split(",")) {
    const dimension = normalizePlanDimension(item);
    if (!dimension || seen.has(dimension)) continue;
    seen.add(dimension);
    dimensions.push(dimension);
  }
  return dimensions;
}

export function canApplyPlanDimensions(value: string, currentDimensions: string[]): boolean {
  const next = parsePlanDimensionsInput(value);
  if (next.length === 0) return false;
  const current = currentDimensions.map(normalizePlanDimension).filter(Boolean);
  if (next.length !== current.length) return true;
  return next.some((dimension, index) => dimension !== current[index]);
}

export type HitlReviewStage = "planner" | "qa";

export function hitlStageFromCurrentNode(currentNode: string | null | undefined): HitlReviewStage | null {
  if (currentNode === "planner_hitl") return "planner";
  if (currentNode === "qa_hitl") return "qa";
  return null;
}

export function fallbackHitlMessage(stage: HitlReviewStage): string {
  return stage === "planner" ? "Planner is ready for review." : "QA review is ready.";
}

export type CompetitorReviewDecision = "keep" | "remove" | "mark_unrelated";

export interface CompetitorReviewRow {
  id: string;
  originalName: string | null;
  name: string;
  decision: CompetitorReviewDecision;
  confidenceLabel: string;
  rationale: string;
  evidenceUrls: string[];
  evidenceTitles: string[];
  note: string;
  manual: boolean;
}

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function normalizeCompetitorName(value: string): string {
  return value.trim().toLowerCase();
}

function confidenceLabel(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

function addUniqueCompetitor(competitors: string[], seen: Set<string>, name: string): void {
  const trimmed = name.trim();
  if (!trimmed) return;
  const normalized = normalizeCompetitorName(trimmed);
  if (seen.has(normalized)) return;
  seen.add(normalized);
  competitors.push(trimmed);
}

export function buildCompetitorReviewRows(
  discovery: CompetitorDiscovery | null | undefined,
  planCompetitors: string[],
): CompetitorReviewRow[] {
  if (discovery?.candidates.length) {
    const selected = new Set(discovery.selected_competitors.map(normalizeCompetitorName));
    return discovery.candidates.map((candidate) => {
      const isSelected = selected.has(normalizeCompetitorName(candidate.name)) || candidate.selected;
      return {
        id: `candidate-${slugify(candidate.name)}`,
        originalName: candidate.name,
        name: candidate.name,
        decision: isSelected ? "keep" : "remove",
        confidenceLabel: confidenceLabel(candidate.confidence),
        rationale: candidate.rationale,
        evidenceUrls: candidate.evidence_urls,
        evidenceTitles: candidate.evidence_titles,
        note: "",
        manual: false,
      };
    });
  }

  return planCompetitors.map((name) => ({
    id: `plan-${slugify(name)}`,
    originalName: name,
    name,
    decision: "keep",
    confidenceLabel: "",
    rationale: "",
    evidenceUrls: [],
    evidenceTitles: [],
    note: "",
    manual: false,
  }));
}

export function updateCompetitorRowName(
  rows: CompetitorReviewRow[],
  id: string,
  name: string,
): CompetitorReviewRow[] {
  return rows.map((row) => (row.id === id ? { ...row, name } : row));
}

export function updateCompetitorRowDecision(
  rows: CompetitorReviewRow[],
  id: string,
  decision: CompetitorReviewDecision,
  note = "",
): CompetitorReviewRow[] {
  return rows.map((row) => (row.id === id ? { ...row, decision, note } : row));
}

export function serializeCompetitorReview(rows: CompetitorReviewRow[]): {
  competitors: string[];
  competitor_edits: CompetitorEdit[];
} {
  const competitors: string[] = [];
  const seen = new Set<string>();
  const competitor_edits: CompetitorEdit[] = [];

  for (const row of rows) {
    const name = row.name.trim();
    const originalName = row.originalName?.trim() ?? "";
    const editName = originalName || name;
    const reason = row.note.trim();

    if (row.decision === "keep") {
      addUniqueCompetitor(competitors, seen, name);

      if (row.manual && name) {
        competitor_edits.push({
          action: "add",
          name,
          reason,
          source_note: "",
        });
      } else if (
        originalName &&
        name &&
        normalizeCompetitorName(originalName) !== normalizeCompetitorName(name)
      ) {
        competitor_edits.push({
          action: "rename",
          name: originalName,
          new_name: name,
          reason,
          source_note: "",
        });
      }
      continue;
    }

    if (!editName) continue;
    competitor_edits.push({
      action: row.decision,
      name: editName,
      reason,
      source_note: "",
    });
  }

  return { competitors, competitor_edits };
}

export function canSavePlanReview(
  rows: CompetitorReviewRow[],
  currentCompetitors: string[],
  dimensionsChanged: boolean,
): boolean {
  const { competitors, competitor_edits } = serializeCompetitorReview(rows);
  if (competitors.length === 0) return false;
  if (dimensionsChanged) return true;
  if (competitor_edits.length > 0) return true;

  const current = currentCompetitors.map(normalizeCompetitorName).filter(Boolean);
  const next = competitors.map(normalizeCompetitorName);
  if (current.length !== next.length) return true;
  return next.some((competitor, index) => competitor !== current[index]);
}
