import { afterEach, expect, it, vi } from 'vitest';
import { subscribeRun } from './client';

afterEach(() => { vi.unstubAllGlobals(); });
it('shares one stream for a run until the last window releases it', () => {
  const close = vi.fn();
  const source = vi.fn(() => ({ addEventListener: vi.fn(), close, onmessage: null }));
  vi.stubGlobal('EventSource', source);
  const a = subscribeRun('stream-test', vi.fn());
  const b = subscribeRun('stream-test', vi.fn());
  expect(source).toHaveBeenCalledTimes(1);
  a(); expect(close).not.toHaveBeenCalled();
  b(); expect(close).toHaveBeenCalledTimes(1);
});
