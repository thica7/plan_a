import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SkillSpec } from "../../api/types";
import { useI18n } from "../../stores/i18n";
import { DimensionsSection } from "./DimensionsSection";

const skills = [
  { name: "feature", description: "Core features and product experience." },
  { name: "security", description: "Security and compliance capabilities." },
] as SkillSpec[];

afterEach(() => useI18n.getState().setLocale("zh-CN"));

describe("dimension display language", () => {
  it("shows Chinese labels and descriptions while selecting the original enum", async () => {
    const toggleDimension = vi.fn();
    render(<DimensionsSection lockedDimensions={["feature"]} selected={["feature"]} selectedScenario={null} skills={skills} toggleDimension={toggleDimension} />);

    expect(screen.getByRole("button", { name: /功能体验/ })).toHaveTextContent("核心功能、产品体验与使用能力");
    await userEvent.setup().click(screen.getByRole("button", { name: /安全合规/ }));
    expect(toggleDimension).toHaveBeenCalledWith("security");
    expect(screen.queryByText("Core features and product experience.")).not.toBeInTheDocument();
  });

  it("switches visible text to English without changing selected values", () => {
    const toggleDimension = vi.fn();
    render(<DimensionsSection lockedDimensions={["feature"]} selected={["feature"]} selectedScenario={null} skills={skills} toggleDimension={toggleDimension} />);
    expect(screen.getByRole("button", { name: /功能体验/ })).toHaveClass("active");

    act(() => useI18n.getState().setLocale("en-US"));
    expect(screen.getByRole("button", { name: /Feature experience/ })).toHaveClass("active");
    expect(screen.getByText(/Core features and product experience./)).toBeInTheDocument();
    expect(toggleDimension).not.toHaveBeenCalled();
  });
});
