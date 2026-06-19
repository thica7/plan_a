import type { ComponentProps } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QaReviewModal } from "./QaReviewModal";

function renderModal(overrides: Partial<ComponentProps<typeof QaReviewModal>> = {}) {
  const props: ComponentProps<typeof QaReviewModal> = {
    message: "QA findings are ready for review.",
    activeDecision: null,
    isSubmitting: false,
    isRedoing: false,
    redoDisabled: false,
    onAccept: vi.fn(),
    onForcePass: vi.fn(),
    onRedo: vi.fn(),
    ...overrides,
  };

  render(<QaReviewModal {...props} />);
  return props;
}

describe("QaReviewModal", () => {
  it("locks every QA decision while a HITL action is submitting", () => {
    renderModal({ activeDecision: "force_pass", isSubmitting: true });

    expect(screen.getByRole("button", { name: /接受|Accept/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /处理中|Submitting/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /重做|Redo/i })).toBeDisabled();
  });
});
