import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { RawSource, RunDetail } from "../../api/types";
import { RunReportReviewStudio } from "./RunReportReviewStudio";

vi.mock("../../api/client", () => ({
  exportReportVersion: vi.fn(),
  startReportApprovalWorkflow: vi.fn(),
}));

const coreSource: RawSource = {
  id: "core-source",
  competitor: "OpenAI",
  covered_competitors: ["OpenAI"],
  dimension: "pricing",
  source_type: "webpage_verified",
  title: "Core source",
  url: "https://example.com/core",
  snippet: "Core evidence.",
  content_hash: "hash-core",
  confidence: 0.9,
  extracted_at: "2026-06-10T00:00:00Z",
};

function makeDetail(): RunDetail {
  return {
    id: "run-1",
    idempotency_key: "key-1",
    workspace_id: "workspace-1",
    project_id: "project-1",
    topic: "AI",
    status: "completed",
    execution_mode: "real",
    output_language: "zh-CN",
    created_at: "2026-06-10T00:00:00Z",
    updated_at: "2026-06-10T00:00:01Z",
    plan: {
      topic: "AI",
      competitors: ["OpenAI"],
      dimensions: ["pricing"],
      complexity: "medium",
      competitor_layer: "L1",
      scenario_id: null,
      scenario_recommended_dimensions: [],
      qa_rule_ids: [],
      homepage_hints: {},
      task_decomposition: [],
      created_at: "2026-06-10T00:00:00Z",
    },
    max_iterations: 2,
    auto_redo_warn_enabled: false,
    hitl_enabled: false,
    report_md: "## Legacy Outline\n\nLegacy body [source:legacy-source].",
    claim_card_bundles: [],
    decision_card_bundle: null,
    section_briefs: [],
    report_artifact: {
      artifact_version: 2,
      run_id: "run-1",
      core_report: {
        layer: "core",
        markdown: "## Core Outline\n\nCore body [source:core-source].",
        sections: [],
      },
      support_appendix: {
        layer: "support",
        markdown: "## Evidence Outline\n\nEvidence body.",
        sections: [],
      },
      audit_log: {
        layer: "audit",
        markdown: "## Audit Outline\n\nAudit body.",
        sections: [],
      },
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
        core_markdown: "## Core Outline\n\nCore body [source:core-source].",
        support_markdown: "## Evidence Outline\n\nEvidence body.",
        audit_markdown: "## Audit Outline\n\nAudit body.",
        full_markdown:
          "## Core Outline\n\nCore body [source:core-source].\n\n## Evidence Outline\n\nEvidence body.\n\n## Audit Outline\n\nAudit body.",
      },
      legacy: { source: "report_artifact_v2", report_md_alias: true },
    },
    raw_sources: [coreSource],
    competitor_kbs: {},
    competitor_knowledge: {},
    competitor_discovery: null,
    comparison_matrix: null,
    qa_findings: [],
    reflections: [],
    revisions: [],
    agent_messages: [],
    tool_call_messages: [],
    trace_spans: [],
    metrics: {
      total_spans: 0,
      total_duration_ms: 0,
      llm_calls: 0,
      search_calls: 0,
      fetch_calls: 0,
      input_tokens_estimate: 0,
      output_tokens_estimate: 0,
      cost_estimate_usd: 0,
      source_coverage_rate: 1,
      verified_source_rate: 1,
      claim_citation_rate: 1,
      schema_pass_rate: 1,
      human_override_rate: 0,
      acceptance_rate: 1,
      qa_issue_count: 0,
      revision_count: 0,
      compliance_redaction_count: 0,
    },
    current_node: null,
    enterprise_projection: null,
  };
}

describe("RunReportReviewStudio artifact layers", () => {
  it("uses the selected artifact layer for the visible outline and source trace", async () => {
    render(
      <RunReportReviewStudio
        detail={makeDetail()}
        reportSources={{ aliases: {}, sources: [coreSource] }}
      />,
    );

    const outline = screen.getByRole("navigation", { name: /outline|大纲/i });
    expect(within(outline).getByText("Core Outline")).toBeInTheDocument();
    expect(within(outline).queryByText("Legacy Outline")).not.toBeInTheDocument();
    expect(screen.queryByText("legacy-source")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Evidence|\u8bc1\u636e/ }));

    expect(within(outline).getByText("Evidence Outline")).toBeInTheDocument();
    expect(within(outline).queryByText("Core Outline")).not.toBeInTheDocument();
  });
});
