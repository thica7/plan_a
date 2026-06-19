import type { ComponentProps } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { CompetitorReviewRow } from "../run-detail/planReview";
import { PlanReviewModal } from "./PlanReviewModal";

const rows: CompetitorReviewRow[] = [
  {
    id: "candidate-1-cursor",
    originalName: "Cursor",
    name: "Cursor",
    decision: "keep",
    initialDecision: "keep",
    confidenceLabel: "91%",
    rationale: "Direct AI IDE",
    evidenceUrls: ["https://cursor.com"],
    evidenceTitles: ["Cursor"],
    note: "",
    manual: false,
  },
];

function renderModal(overrides: Partial<ComponentProps<typeof PlanReviewModal>> = {}) {
  const props: ComponentProps<typeof PlanReviewModal> = {
    message: "Planner is ready for review.",
    canApplyChanges: true,
    competitorRows: rows,
    dimensions: "pricing, feature",
    onAddCompetitor: vi.fn(),
    onCompetitorDecisionChange: vi.fn(),
    onCompetitorNameChange: vi.fn(),
    onCompetitorNoteChange: vi.fn(),
    onDeleteCompetitor: vi.fn(),
    onDimensionsChange: vi.fn(),
    onAccept: vi.fn(),
    onApply: vi.fn(),
    ...overrides,
  };

  render(<PlanReviewModal {...props} />);
  return props;
}

describe("PlanReviewModal", () => {
  it("renders editable competitor review rows", () => {
    renderModal();

    expect(screen.getByText("Competitors")).toBeInTheDocument();
    expect(screen.getByLabelText("Competitor 1 name")).toHaveValue("Cursor");
    expect(screen.getByLabelText("Competitor 1 decision")).toHaveValue("keep");
    expect(screen.getByRole("link", { name: "Cursor" })).toHaveAttribute("href", "https://cursor.com");
  });

  it("emits row edit callbacks from the compact table", async () => {
    const user = userEvent.setup();
    const props = renderModal();

    fireEvent.change(screen.getByLabelText("Competitor 1 name"), { target: { value: "Cursor AI" } });
    fireEvent.change(screen.getByLabelText("Competitor 1 decision"), { target: { value: "mark_unrelated" } });
    fireEvent.change(screen.getByLabelText("Competitor 1 note"), { target: { value: "Wrong segment" } });
    await user.click(screen.getByRole("button", { name: "Remove Cursor" }));
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(props.onCompetitorNameChange).toHaveBeenLastCalledWith("candidate-1-cursor", "Cursor AI");
    expect(props.onCompetitorDecisionChange).toHaveBeenCalledWith("candidate-1-cursor", "mark_unrelated");
    expect(props.onCompetitorNoteChange).toHaveBeenLastCalledWith("candidate-1-cursor", "Wrong segment");
    expect(props.onDeleteCompetitor).toHaveBeenCalledWith("candidate-1-cursor");
    expect(props.onAddCompetitor).toHaveBeenCalledTimes(1);
  });

  it("disables apply until the plan has a real edit", () => {
    renderModal({ canApplyChanges: false });

    expect(screen.getByTitle("Edit the plan to enable this action")).toBeDisabled();
  });
});
