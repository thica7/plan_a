import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { RunDetail } from '../../api/types';
import { DimensionEvidencePanel } from './DimensionEvidencePanel';

function detail(): RunDetail {
  return {
    id: 'partial', status: 'completed_with_blockers', max_iterations: 2, revisions: [],
    plan: { competitors: ['Notion', 'Coda'], dimensions: ['feature', 'pricing'] },
    raw_sources: [{ id: 'notion-feature', competitor: 'Notion', covered_competitors: ['Notion'], dimension: 'feature', source_type: 'webpage_verified', confidence: .8, title: '协作说明', url: 'https://www.notion.com/help/collaborate-with-people', snippet: '多人可同时编辑同一页面。' }],
    qa_findings: [{ id: 'coda-price', severity: 'blocker', target_agent: 'collector', target_competitor: 'Coda', target_subagent: 'pricing', problem: 'Coda 当前价格缺少可核验依据。', redo_scope: { kind: 'collector', target_competitor: 'Coda', target_subagent: 'pricing' } }],
  } as unknown as RunDetail;
}

describe('dimension evidence', () => {
  it('labels demo fixtures separately from real verification', () => {
    render(<DimensionEvidencePanel detail={{ ...detail(), execution_mode: 'demo' }} />);
    expect(screen.getAllByText('演示内容（非真实核验）')).toHaveLength(4);
    expect(screen.queryByText('已核验内容')).not.toBeInTheDocument();
  });
  it('shows supported content and product-specific unknowns', () => {
    render(<DimensionEvidencePanel detail={detail()} />);
    expect(screen.getByText('多人可同时编辑同一页面。')).toBeInTheDocument();
    expect(screen.getByText('Coda 当前价格缺少可核验依据。')).toBeInTheDocument();
    expect(screen.getAllByText('尚无已核验内容').length).toBe(3);
    expect(screen.getByRole('link', { name: '协作说明' })).toHaveAttribute('href', 'https://www.notion.com/help/collaborate-with-people');
  });
  it('repairs only selected branch issue IDs', async () => {
    const repair = vi.fn().mockResolvedValue(true);
    render(<DimensionEvidencePanel detail={detail()} onRepair={repair} />);
    await userEvent.click(screen.getByRole('button', { name: '定向补证：Coda / 价格与成本' }));
    expect(repair).toHaveBeenCalledWith(['coda-price']);
    expect(await screen.findByText('补证任务已启动，请查看任务进度。')).toBeInTheDocument();
  });
  it('disables repair while running or out of redo rounds', () => {
    const d = detail(); d.status = 'running';
    const { rerender } = render(<DimensionEvidencePanel detail={d} onRepair={vi.fn()} />);
    expect(screen.getByRole('button')).toBeDisabled();
    d.status = 'completed_with_blockers'; d.max_iterations = 0;
    rerender(<DimensionEvidencePanel detail={d} onRepair={vi.fn()} />);
    expect(screen.getByRole('button')).toBeDisabled();
  });
  it('reports rejected repair without claiming success', async () => {
    render(<DimensionEvidencePanel detail={detail()} onRepair={vi.fn().mockResolvedValue(false)} />);
    await userEvent.click(screen.getByRole('button'));
    expect(await screen.findByText('补证启动失败，请查看任务错误并重试。')).toBeInTheDocument();
    expect(screen.queryByText('补证任务已启动，请查看任务进度。')).not.toBeInTheDocument();
  });
  it('permits another repair when the prior task finishes', async () => {
    const d = detail(); const repair = vi.fn().mockResolvedValue(true);
    const { rerender } = render(<DimensionEvidencePanel detail={d} onRepair={repair} />);
    await userEvent.click(screen.getByRole('button'));
    expect(screen.getByRole('button')).toBeDisabled();
    rerender(<DimensionEvidencePanel detail={{ ...d, status: 'running' }} onRepair={repair} />);
    rerender(<DimensionEvidencePanel detail={{ ...d, status: 'completed_with_blockers', updated_at: '2026-10-10T10:00:00Z' }} onRepair={repair} />);
    expect(screen.getByRole('button')).toBeEnabled();
  });
  it('keeps repair scopes separate for missing whole dimensions', async () => {
    const d = detail(); d.qa_findings[0].target_competitor = null;
    d.qa_findings[0].redo_scope.target_competitor = null;
    const repair = vi.fn().mockResolvedValue(true);
    render(<DimensionEvidencePanel detail={d} onRepair={repair} />);
    const section = screen.getByRole('region', { name: '价格与成本' });
    await userEvent.click(within(section).getByRole('button', { name: '定向补证：价格与成本' }));
    expect(repair).toHaveBeenCalledTimes(1);
  });
  it('excludes retired sources from verified content', () => {
    const d = detail(); d.evidence_retired_source_ids = ['notion-feature'];
    render(<DimensionEvidencePanel detail={d} />);
    expect(screen.queryByText('多人可同时编辑同一页面。')).not.toBeInTheDocument();
  });
});
