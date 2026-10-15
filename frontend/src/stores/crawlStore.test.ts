import { afterEach, expect, it, vi } from 'vitest';
import { useCrawlStore } from './crawlStore';

afterEach(() => { useCrawlStore.getState().stopPolling(); vi.unstubAllGlobals(); });
it('invalidates an old jobs request and stops its polling after switching scope', async () => {
  let finish!: (value: Response) => void;
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { finish = resolve; })));
  useCrawlStore.getState().setScope({ projectId: 'a', includeWorkspaceLibrary: true });
  const pending = useCrawlStore.getState().fetchJobs();
  useCrawlStore.getState().setScope({ projectId: 'b', includeWorkspaceLibrary: false });
  finish(new Response(JSON.stringify([{ id: 'old', status: 'running' }]))); await pending;
  expect(useCrawlStore.getState().jobs).toEqual([]);
  expect(useCrawlStore.getState().pollingIntervalId).toBeNull();
});
it('never clones a task under the name retry or calls absent delete endpoints', async () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
  useCrawlStore.getState().setScope({ projectId: 'a', includeWorkspaceLibrary: true });
  useCrawlStore.setState({ jobs: [{ id: 'public', project_id: null, url: 'https://example.com' }] as any });
  await useCrawlStore.getState().retryJob('public');
  await useCrawlStore.getState().deleteJob('public');
  expect(fetcher).not.toHaveBeenCalled();
  expect(useCrawlStore.getState().error).toContain('尚未提供');
});

it('keeps scope on polling and rejects an in-flight poll after a scope change', async () => {
  vi.useFakeTimers();
  try {
    let finishPoll!: (value: Response) => void;
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify([{ id: 'active', project_id: 'a', status: 'running' }]))).mockImplementationOnce(() => new Promise(resolve => { finishPoll = resolve; }));
    vi.stubGlobal('fetch', fetcher);
    useCrawlStore.getState().setScope({ projectId: 'a', includeWorkspaceLibrary: true });
    await useCrawlStore.getState().fetchJobs();
    expect(useCrawlStore.getState().pollingIntervalId).not.toBeNull();
    await vi.advanceTimersByTimeAsync(3000);
    expect(fetcher.mock.calls[1][0]).toBe('/api/crawl/jobs?project_id=a&include_workspace_library=true');
    useCrawlStore.getState().setScope({ projectId: 'b', includeWorkspaceLibrary: false });
    finishPoll(new Response(JSON.stringify([{ id: 'late-poll', status: 'running' }])));
    await Promise.resolve(); await Promise.resolve();
    expect(useCrawlStore.getState().jobs).toEqual([]);
    expect(useCrawlStore.getState().pollingIntervalId).toBeNull();
  } finally { vi.useRealTimers(); }
});
