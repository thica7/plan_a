import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DepthSection } from "./DepthSection";
import { ResearchDepthSection } from "./ResearchDepthSection";
import { CollaborationSection } from "./CollaborationSection";

describe("new run research modes", () => {
  it("describes L1/L2/L3 as research perspectives", () => {
    render(<DepthSection selectedLayer="L1" updateSelectedLayer={vi.fn()} />);
    expect(screen.getByText("研究视角")).toBeInTheDocument();
    expect(screen.getByText("直接对比")).toBeInTheDocument();
    expect(screen.getByText("相邻替代")).toBeInTheDocument();
    expect(screen.getByText("市场全景")).toBeInTheDocument();
  });

  it("shows actual budget caps and changes depth selection", async () => {
    const onChange = vi.fn();
    render(<ResearchDepthSection researchDepth="standard" setResearchDepth={onChange} />);
    expect(screen.getByText(/2 个竞品.*6 个切片.*2 个来源.*60 次/)).toBeInTheDocument();
    expect(screen.getByText(/5 个竞品.*12 个切片.*3 个来源.*120 次/)).toBeInTheDocument();
    expect(screen.getByText(/8 个竞品.*24 个切片.*5 个来源.*160 次/)).toBeInTheDocument();
    expect(screen.getByText(/部署配置可能进一步收紧/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: /快速研究/ }));
    expect(onChange).toHaveBeenCalledWith("quick");
  });

  it("keeps collaboration independent from the data source and explains pauses", async () => {
    const onChange = vi.fn();
    render(<CollaborationSection collaborationMode="ai" setCollaborationMode={onChange} />);
    expect(screen.getByText(/无需等待人工审核/)).toBeInTheDocument();
    expect(screen.getByText(/计划、证据和 QA/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: /半人工协作/ }));
    expect(onChange).toHaveBeenCalledWith("assisted");
  });
});
