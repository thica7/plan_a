import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ReportView } from "./ReportView";

const evidenceLabel = /Evidence|\u8bc1\u636e/;

const reportArtifact = {
  artifact_version: 2,
  run_id: "run-1",
  core_report: { layer: "core", markdown: "## Core Report\n\nCore body.", sections: [] },
  support_appendix: { layer: "support", markdown: "## Evidence\n\nEvidence body.", sections: [] },
  audit_log: { layer: "audit", markdown: "## Audit\n\nAudit body.", sections: [] },
  claim_card_bundles: [],
  decision_card_bundle: null,
  section_briefs: [],
  quality: {
    core_gate: {},
    support_gate: {},
    audit_gate: {},
    warnings: [],
    blockers: [],
    revision_count: 0,
  },
  render_cache: {
    core_markdown: "## Core Report\n\nCore body.",
    support_markdown: "## Evidence\n\nEvidence body.",
    audit_markdown: "## Audit\n\nAudit body.",
    full_markdown: "## Core Report\n\nCore body.\n\n## Evidence\n\nEvidence body.\n\n## Audit\n\nAudit body.",
  },
  legacy: { source: "report_artifact_v2", report_md_alias: true },
} as const;

describe("ReportView artifact layers", () => {
  it("localizes missing citation labels without changing the source identifier", () => {
    render(<ReportView markdown="Claim [source:missing-id]." sources={[]} />);
    expect(screen.getByRole('link', { name: '缺失 1' })).toHaveAttribute('href', '#missing-source-missing-id');
  });
  it("localizes generated footnote labels while preserving footnote prose and links", () => {
    render(<ReportView markdown={"Original claim.[^1]\n\n[^1]: Source quotation. [Original source](https://example.com/evidence)"} sources={[]} />);
    expect(screen.getByRole("heading", { name: "脚注" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "返回引用 1" })).toHaveAttribute("href", "#user-content-fnref-1");
    expect(screen.getByRole("link", { name: "Original source" })).toHaveAttribute("href", "https://example.com/evidence");
    expect(screen.getByText(/Source quotation./)).toBeInTheDocument();
  });
  it("defaults to core report and can switch to evidence", async () => {
    render(<ReportView markdown="## Legacy" reportArtifact={reportArtifact} sources={[]} />);

    expect(screen.getByText("Core body.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: evidenceLabel }));
    expect(screen.getByText("Evidence body.")).toBeInTheDocument();
  });

  it("renders legacy markdown without layer controls when no artifact exists", () => {
    render(<ReportView markdown={"## Legacy\n\nLegacy body."} sources={[]} />);

    expect(screen.getByText("Legacy body.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: evidenceLabel })).not.toBeInTheDocument();
  });
});
