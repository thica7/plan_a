import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { DecisionReplayReport, RawSource, RunDetail, TraceSpan } from "../../api/types";
import { RunReviewOverview } from "./RunReviewOverview";
import { RunReportReviewStudio } from "./RunReportReviewStudio";

const recordedAt = "2026-09-29T12:00:00Z";
const span = {
  id: "span-1",
  agent: "collector",
  subagent: "feature::Acme",
  kind: "tool",
  name: "fetch_page",
  status: "ok",
  duration_ms: 12,
  created_at: recordedAt,
  metadata: {},
} as TraceSpan;

function runDetail(traceSpans: TraceSpan[]): RunDetail {
  return {
    id: "run-1",
    status: "completed",
    current_node: null,
    report_md: "Original report prose.",
    plan: { competitor_layer: "L1", scenario_id: null, qa_rule_ids: [], task_decomposition: [] },
    metrics: { verified_source_rate: 1, source_coverage_rate: 1, claim_citation_rate: 1, schema_pass_rate: 1 },
    raw_sources: [],
    qa_findings: [],
    reflections: [],
    revisions: [],
    agent_messages: [],
    trace_spans: traceSpans,
    comparison_matrix: null,
    enterprise_projection: null,
  } as unknown as RunDetail;
}

describe("RunReviewOverview timeline labels", () => {
  it('opens the current run report source without jumping to another reader with the same ID', async () => {
    const source = { id: 'shared-source', title: '共享来源', dimension: 'pricing', confidence: 0.9, source_type: 'webpage_verified', url: 'https://example.com/evidence', covered_competitors: [], metadata: {}, content_hash: 'hash' } as unknown as RawSource;
    const detail = { ...runDetail([]), raw_sources: [source], report_md: '当前报告 [source:shared-source]' };
    const reportSources = { aliases: {}, sources: [source] };
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    function CurrentRun() {
      const location = useLocation();
      return <><output>{location.pathname + location.search + location.hash}</output>{new URLSearchParams(location.search).get('view') === 'report'
        ? <RunReportReviewStudio detail={detail} reportSources={reportSources} />
        : <RunReviewOverview decisionReplay={null} detail={detail} events={[]} isRedoing={false} onRedo={vi.fn()} onViewChange={vi.fn()} qualityComparison={null} redoLimitReached={false} reflectionItems={[]} reportSources={reportSources} />}</>;
    }
    const { container } = render(<><MemoryRouter initialEntries={['/runs/other?view=report']}><RunReportReviewStudio detail={detail} reportSources={reportSources} /></MemoryRouter><MemoryRouter initialEntries={['/runs/run-1?view=overview&filter=saved']}><CurrentRun /></MemoryRouter></>);
    const otherTarget = container.querySelector('[id="source-shared-source"]');
    await userEvent.click(screen.getByRole('link', { name: /共享来源/ }));
    expect(screen.getByText('/runs/run-1?view=report&filter=saved#source-shared-source')).toBeInTheDocument();
    const currentReport = container.querySelectorAll('.run-report-review-studio')[1] as HTMLElement;
    const target = currentReport.querySelector('[id="source-shared-source"]');
    expect(within(currentReport).getByRole('button', { name: '目录与来源' })).toHaveAttribute('aria-expanded', 'true');
    expect(target).toHaveClass('active');
    expect(scroll.mock.instances[scroll.mock.instances.length - 1]).toBe(target);
    expect(scroll.mock.instances).not.toContain(otherTarget);
  });

  it.each(["replay", "span"])("shows translated composite dimensions for %s records and keeps product names intact", (source) => {
    const decisionReplay = source === "replay" ? {
      events: [{
        id: "event-1", event_type: "tool.called", agent: "collector", subagent: "feature::Acme",
        message: "Original system detail.", created_at: recordedAt,
      }],
    } as DecisionReplayReport : null;

    render(<RunReviewOverview
      decisionReplay={decisionReplay}
      detail={runDetail(source === "span" ? [span] : [])}
      events={[]}
      isRedoing={false}
      onRedo={vi.fn()}
      onViewChange={vi.fn()}
      qualityComparison={null}
      redoLimitReached={false}
      reflectionItems={[]}
      reportSources={{ aliases: {}, sources: [] }}
    />);

    expect(screen.getByText(/资料采集\/功能体验 \/ Acme/)).toBeInTheDocument();
    expect(screen.queryByText(/feature::Acme/)).not.toBeInTheDocument();
    if (source === "replay") expect(screen.getByText(/Original system detail\./)).toBeInTheDocument();
  });
});
