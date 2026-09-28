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
});
