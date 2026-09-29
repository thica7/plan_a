import { describe, expect, it } from 'vitest';
import { getRunStore } from './run';
import type { RunDetail } from '../api/types';

describe('independent run sessions', () => {
  it('does not overwrite another report when a window receives an event', () => {
    const a = getRunStore('window-a');
    const b = getRunStore('window-b');
    a.getState().setDetail({ id: 'window-a', report_md: 'A' } as RunDetail);
    b.getState().setDetail({ id: 'window-b', report_md: 'B' } as RunDetail);
    a.getState().addEvent({ id: 1, run_id: 'window-a', type: 'report_updated', payload: { report_md: 'A2' }, message: '', created_at: '' });
    expect(a.getState().detail?.report_md).toBe('A2');
    expect(b.getState().detail?.report_md).toBe('B');
    a.getState().reset();
    expect(b.getState().detail?.report_md).toBe('B');
  });

  it('keeps the full detail when an evidence interrupt carries only run status', () => {
    const store = getRunStore('evidence-run');
    store.getState().setDetail({
      id: 'evidence-run', status: 'running', current_node: 'collector',
      plan: { competitors: ['Alpha'], dimensions: ['pricing'] }, report_md: 'Existing report',
    } as RunDetail);

    store.getState().addEvent({
      id: 2, run_id: 'evidence-run', type: 'interrupt',
      payload: { stage: 'evidence', run: { id: 'evidence-run', status: 'interrupted', current_node: 'evidence_hitl' } },
      message: 'Review evidence', created_at: '',
    });

    expect(store.getState().detail).toMatchObject({
      status: 'interrupted', current_node: 'evidence_hitl',
      plan: { competitors: ['Alpha'], dimensions: ['pricing'] }, report_md: 'Existing report',
    });
    store.getState().reset();
  });

  it('does not create an incomplete detail from an early evidence interrupt', () => {
    const store = getRunStore('early-evidence');
    store.getState().reset();
    store.getState().addEvent({
      id: 3, run_id: 'early-evidence', type: 'interrupt',
      payload: { stage: 'evidence', run: { id: 'early-evidence', status: 'interrupted', current_node: 'evidence_hitl' } },
      message: 'Review evidence', created_at: '',
    });
    expect(store.getState().detail).toBeUndefined();
    store.getState().reset();
  });

  it('ignores a duplicate evidence interrupt after the run has resumed', () => {
    const store = getRunStore('replayed-evidence');
    store.getState().reset();
    const oldInterrupt = {
      id: 4, run_id: 'replayed-evidence', type: 'interrupt' as const,
      payload: { stage: 'evidence', run: { id: 'replayed-evidence', status: 'interrupted' as const, current_node: 'evidence_hitl' } },
      message: 'Review evidence', created_at: '2026-09-29T10:00:01Z',
    };
    store.getState().setDetail({ id: 'replayed-evidence', status: 'running', current_node: 'collector', updated_at: '2026-09-29T10:00:00Z', plan: {} } as RunDetail);
    store.getState().addEvent(oldInterrupt);
    store.getState().setDetail({ id: 'replayed-evidence', status: 'interrupted', current_node: 'qa_hitl', updated_at: '2026-09-29T10:00:05Z', plan: {} } as RunDetail);
    store.getState().addEvent(oldInterrupt);
    expect(store.getState().detail?.current_node).toBe('qa_hitl');
    store.getState().reset();
  });

  it('does not apply a historical evidence interrupt over a newer loaded run', () => {
    const store = getRunStore('late-replay');
    store.getState().reset();
    store.getState().setDetail({ id: 'late-replay', status: 'interrupted', current_node: 'qa_hitl', updated_at: '2026-09-29T10:00:05Z', plan: {} } as RunDetail);
    store.getState().addEvent({
      id: 5, run_id: 'late-replay', type: 'interrupt',
      payload: { stage: 'evidence', run: { id: 'late-replay', status: 'interrupted', current_node: 'evidence_hitl' } },
      message: 'Review evidence', created_at: '2026-09-29T10:00:01Z',
    });
    expect(store.getState().detail?.current_node).toBe('qa_hitl');
    expect(store.getState().events).toHaveLength(1);
    store.getState().reset();
  });

  it('does not replay an old report update over a newer loaded report', () => {
    const store = getRunStore('late-report');
    store.getState().reset();
    store.getState().setDetail({
      id: 'late-report', updated_at: '2026-09-29T10:00:05Z',
      report_md: 'New report', report_artifact: { artifact_version: 2 },
    } as RunDetail);
    store.getState().addEvent({
      id: 6, run_id: 'late-report', type: 'report_updated',
      payload: { report_md: 'Old report', report_artifact: null },
      message: 'Old update', created_at: '2026-09-29T10:00:01Z',
    });
    expect(store.getState().detail?.report_md).toBe('New report');
    expect(store.getState().detail?.report_artifact).toEqual({ artifact_version: 2 });
    expect(store.getState().events).toHaveLength(1);
    store.getState().reset();
  });

  it('uses submillisecond order for report updates from the same millisecond', () => {
    const store = getRunStore('micro-report');
    store.getState().reset();
    store.getState().setDetail({ id: 'micro-report', updated_at: '2026-09-29T10:00:01.123900Z', report_md: 'New report' } as RunDetail);
    store.getState().addEvent({
      id: 7, run_id: 'micro-report', type: 'report_updated',
      payload: { report_md: 'Old report' }, message: '', created_at: '2026-09-29T10:00:01.123100Z',
    });
    expect(store.getState().detail?.report_md).toBe('New report');
    store.getState().reset();
    store.getState().setDetail({ id: 'micro-report', updated_at: '2026-09-29T10:00:01.123100Z', report_md: 'Old report' } as RunDetail);
    store.getState().addEvent({
      id: 8, run_id: 'micro-report', type: 'report_updated',
      payload: { report_md: 'New report' }, message: '', created_at: '2026-09-29T10:00:01.123900Z',
    });
    expect(store.getState().detail?.report_md).toBe('New report');
    store.getState().reset();
  });

  it('keeps a newer detail when an older HTTP snapshot arrives', () => {
    const store = getRunStore('late-http');
    store.getState().reset();
    store.getState().setDetail({ id: 'late-http', current_node: 'qa_hitl', updated_at: '2026-09-29T10:00:05Z' } as RunDetail);
    store.getState().setDetail({ id: 'late-http', current_node: 'evidence_hitl', updated_at: '2026-09-29T10:00:01Z' } as RunDetail);
    expect(store.getState().detail?.current_node).toBe('qa_hitl');
    store.getState().reset();
  });

  it('accepts HTTP snapshots without usable timestamps for legacy fixtures', () => {
    const store = getRunStore('legacy-http');
    store.getState().reset();
    store.getState().setDetail({ id: 'legacy-http', report_md: 'Before', updated_at: '2026-09-29T10:00:05Z' } as RunDetail);
    store.getState().setDetail({ id: 'legacy-http', report_md: 'Without date' } as RunDetail);
    expect(store.getState().detail?.report_md).toBe('Without date');
    store.getState().setDetail({ id: 'legacy-http', report_md: 'Invalid date', updated_at: 'unknown' } as RunDetail);
    expect(store.getState().detail?.report_md).toBe('Invalid date');
    store.getState().reset();
  });

  it('merges the numeric evidence round from an SSE interrupt payload', () => {
    const store = getRunStore('round-sse');
    store.getState().reset();
    store.getState().setDetail({
      id: 'round-sse', status: 'interrupted', current_node: 'evidence_hitl',
      updated_at: '2026-09-29T10:00:01Z', evidence_repair_rounds: 0,
    } as RunDetail);
    store.getState().addEvent({
      id: 9, run_id: 'round-sse', type: 'interrupt', message: 'New round',
      payload: {
        stage: 'evidence', evidence_repair_rounds: 1,
        run: { id: 'round-sse', status: 'interrupted', current_node: 'evidence_hitl' },
      },
      created_at: '2026-09-29T10:00:02Z',
    });
    expect(store.getState().detail?.evidence_repair_rounds).toBe(1);
    store.getState().reset();
  });
});
