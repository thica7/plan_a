import { describe, expect, it } from "vitest";
import type { CompetitorDiscovery } from "../../api/types";
import {
  canApplyPlanDimensions,
  buildCompetitorReviewRows,
  canSavePlanReview,
  fallbackHitlMessage,
  hitlStageFromCurrentNode,
  normalizePlanDimension,
  parsePlanDimensionsInput,
  serializeCompetitorReview,
  updateCompetitorRowDecision,
  updateCompetitorRowName,
  type CompetitorReviewRow,
} from "./planReview";

const discovery: CompetitorDiscovery = {
  query: "AI IDE competitors",
  selected_competitors: ["Cursor", "Replit"],
  rationale: "Planner discovery",
  created_at: "2026-06-10T00:00:00Z",
  candidates: [
    {
      name: "Cursor",
      rank: 1,
      selected: true,
      rationale: "Direct AI IDE",
      evidence_titles: ["Cursor"],
      evidence_urls: ["https://cursor.com"],
      confidence: 0.91,
    },
    {
      name: "Replit",
      rank: 2,
      selected: true,
      rationale: "Adjacent platform",
      evidence_titles: ["Replit"],
      evidence_urls: ["https://replit.com"],
      confidence: 0.55,
    },
  ],
};

describe("plan review dimension helpers", () => {
  it("normalizes reviewer dimension input with the backend key shape", () => {
    expect(normalizePlanDimension(" Market Landscape ")).toBe("market_landscape");
    expect(parsePlanDimensionsInput("Pricing, feature, pricing, buyer persona")).toEqual([
      "pricing",
      "feature",
      "buyer_persona",
    ]);
  });

  it("only enables apply when reviewer dimensions actually change", () => {
    const current = ["pricing", "feature", "persona"];

    expect(canApplyPlanDimensions(" pricing, feature, persona ", current)).toBe(false);
    expect(canApplyPlanDimensions("pricing, feature, persona, review", current)).toBe(true);
    expect(canApplyPlanDimensions("feature, pricing, persona", current)).toBe(true);
    expect(canApplyPlanDimensions("", current)).toBe(false);
  });

  it("restores the visible HITL review stage from persisted current_node", () => {
    expect(hitlStageFromCurrentNode("planner_hitl")).toBe("planner");
    expect(hitlStageFromCurrentNode("qa_hitl")).toBe("qa");
    expect(hitlStageFromCurrentNode("writer")).toBeNull();
    expect(fallbackHitlMessage("planner")).toBe("Planner is ready for review.");
    expect(fallbackHitlMessage("qa")).toBe("QA review is ready.");
  });
});

describe("competitor review helpers", () => {
  it("builds review rows from discovery candidates", () => {
    expect(buildCompetitorReviewRows(discovery, ["Cursor"])).toEqual([
      {
        id: "candidate-1-cursor",
        originalName: "Cursor",
        name: "Cursor",
        decision: "keep",
        confidenceLabel: "91%",
        rationale: "Direct AI IDE",
        evidenceUrls: ["https://cursor.com"],
        evidenceTitles: ["Cursor"],
        note: "",
        manual: false,
      },
      {
        id: "candidate-2-replit",
        originalName: "Replit",
        name: "Replit",
        decision: "keep",
        confidenceLabel: "55%",
        rationale: "Adjacent platform",
        evidenceUrls: ["https://replit.com"],
        evidenceTitles: ["Replit"],
        note: "",
        manual: false,
      },
    ]);
  });

  it("serializes removed competitors and excludes them from final competitors", () => {
    const rows = updateCompetitorRowDecision(
      buildCompetitorReviewRows(discovery, []),
      "candidate-2-replit",
      "remove",
      "Not a direct IDE",
    );

    expect(serializeCompetitorReview(rows)).toEqual({
      competitors: ["Cursor"],
      competitor_edits: [
        {
          action: "remove",
          name: "Replit",
          reason: "Not a direct IDE",
          source_note: "",
        },
      ],
    });
  });

  it("serializes manual additions and includes them in final competitors", () => {
    const rows: CompetitorReviewRow[] = [
      ...buildCompetitorReviewRows(discovery, []),
      {
        id: "manual-windsurf",
        originalName: null,
        name: "Windsurf",
        decision: "keep",
        confidenceLabel: "",
        rationale: "",
        evidenceUrls: [],
        evidenceTitles: [],
        note: "Missing from discovery",
        manual: true,
      },
    ];

    expect(serializeCompetitorReview(rows)).toEqual({
      competitors: ["Cursor", "Replit", "Windsurf"],
      competitor_edits: [
        {
          action: "add",
          name: "Windsurf",
          reason: "Missing from discovery",
          source_note: "",
        },
      ],
    });
  });

  it("serializes renamed competitors", () => {
    const rows = updateCompetitorRowName(
      buildCompetitorReviewRows(discovery, []),
      "candidate-2-replit",
      "Replit Agent",
    );

    expect(serializeCompetitorReview(rows)).toEqual({
      competitors: ["Cursor", "Replit Agent"],
      competitor_edits: [
        {
          action: "rename",
          name: "Replit",
          new_name: "Replit Agent",
          reason: "",
          source_note: "",
        },
      ],
    });
  });

  it("serializes unrelated competitors and excludes them from final competitors", () => {
    const rows = updateCompetitorRowDecision(
      buildCompetitorReviewRows(discovery, []),
      "candidate-2-replit",
      "mark_unrelated",
      "Developer hosting rather than IDE",
    );

    expect(serializeCompetitorReview(rows)).toEqual({
      competitors: ["Cursor"],
      competitor_edits: [
        {
          action: "mark_unrelated",
          name: "Replit",
          reason: "Developer hosting rather than IDE",
          source_note: "",
        },
      ],
    });
  });

  it("enables save only when review changes produce competitors or dimension changes exist", () => {
    const rows = buildCompetitorReviewRows(discovery, []);

    expect(canSavePlanReview(rows, ["Cursor", "Replit"], false)).toBe(false);
    expect(canSavePlanReview(rows, ["Cursor", "Replit"], true)).toBe(true);
    expect(canSavePlanReview(rows, ["Cursor"], false)).toBe(true);

    const removedRows = rows.map((row) => ({ ...row, decision: "remove" as const }));
    expect(canSavePlanReview(removedRows, ["Cursor", "Replit"], true)).toBe(false);
    expect(canSavePlanReview(removedRows, ["Cursor", "Replit"], false)).toBe(false);

    const editedRows = updateCompetitorRowDecision(rows, "candidate-2-replit", "remove", "Not a fit");
    expect(canSavePlanReview(editedRows, ["Cursor", "Replit"], false)).toBe(true);
  });

  it("keeps row ids unique when candidate names slugify to the same value", () => {
    const rows = buildCompetitorReviewRows(
      {
        ...discovery,
        selected_competitors: ["A&B", "A B", "竞品"],
        candidates: [
          { ...discovery.candidates[0], name: "A&B" },
          { ...discovery.candidates[1], name: "A B" },
          { ...discovery.candidates[1], name: "竞品" },
        ],
      },
      [],
    );

    expect(rows.map((row) => row.id)).toEqual([
      "candidate-1-a-b",
      "candidate-2-a-b",
      "candidate-3-name",
    ]);

    const updatedRows = updateCompetitorRowDecision(rows, "candidate-2-a-b", "remove");
    expect(updatedRows.map((row) => row.decision)).toEqual(["keep", "remove", "keep"]);
  });
});
