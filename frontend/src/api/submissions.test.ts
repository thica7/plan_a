import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cancelSubmission, createSubmission, getQuotaLedger, getSubmission, getSubmissionRuntime, listSubmissions, retrySubmissionDispatch, SubmissionApiError, submissionErrorKey } from './submissions';
import type { SubmissionCreateRequest } from './types';
const transport = vi.fn();
beforeEach(() => { transport.mockReset().mockResolvedValue(new Response('{}')); vi.stubGlobal('fetch', transport); localStorage.clear(); });
afterEach(() => { vi.unstubAllGlobals(); });

it('preserves same-origin identity headers, explicit submission envelope and abort signal', async () => {
  localStorage.setItem('competiscope.authToken', 'test-token');
  localStorage.setItem('competiscope.userId', 'test-user');
  localStorage.setItem('competiscope.workspaceId', 'space A');
  const signal = new AbortController().signal;
  const body: SubmissionCreateRequest = { idempotency_key: 'intent', request: { workspace_id: 'space A', topic: '研究', dimensions: ['pricing'], execution_mode: 'demo', output_language: 'zh-CN' } };
  await createSubmission(body, signal);
  const [path, init] = transport.mock.calls[0];
  expect(path).toBe('/api/task-submissions');
  expect(init.credentials).toBe('same-origin');
  expect(init.signal).toBe(signal);
  expect(new Headers(init.headers).get('Authorization')).toBe('Bearer test-token');
  expect(new Headers(init.headers).get('X-User-Id')).toBe('test-user');
  expect(new Headers(init.headers).get('X-Workspace-Id')).toBe('space A');
  expect(JSON.parse(init.body)).toEqual(body);
});

it('encodes identities, opaque cursors and period queries for all read/mutation endpoints', async () => {
  const cases: [() => Promise<unknown>, string, string | undefined][] = [
    [() => listSubmissions({ workspaceId: 'a/b', status: 'pending', cursor: 'x+/=' }), '/api/task-submissions?workspace_id=a%2Fb&status=pending&cursor=x%2B%2F%3D&limit=20', undefined],
    [() => getSubmission('id/a', 'a/b'), '/api/task-submissions/id%2Fa?workspace_id=a%2Fb', undefined],
    [() => cancelSubmission('id/a', 'a/b'), '/api/task-submissions/id%2Fa/cancel?workspace_id=a%2Fb', 'POST'],
    [() => retrySubmissionDispatch('id/a', 'a/b'), '/api/task-submissions/id%2Fa/retry-dispatch?workspace_id=a%2Fb', 'POST'],
    [() => getQuotaLedger({ workspaceId: 'a/b', periodStart: '2026-10-01T00:00:00Z', cursor: 'q+/' }), '/api/workspaces/a%2Fb/quota-ledger?period_start=2026-10-01T00%3A00%3A00Z&cursor=q%2B%2F&limit=20', undefined],
    [() => getSubmissionRuntime(), '/api/runtime', undefined],
  ];
  for (const [call, path, method] of cases) {
    transport.mockResolvedValueOnce(new Response('{}'));
    await call();
    expect(transport).toHaveBeenLastCalledWith(path, expect.objectContaining({ credentials: 'same-origin' }));
    expect(transport.mock.calls[transport.mock.calls.length - 1][1].method).toBe(method);
  }
});

it.each([
  [403, {}, 'submissions.error.permission'], [404, {}, 'submissions.error.notFound'],
  [409, { code: 'dispatch_conflict' }, 'submissions.error.conflict'], [429, { code: 'quota_exceeded' }, 'submissions.error.quota'],
  [503, { code: 'task_center_disabled' }, 'submissions.error.disabled'], [503, { code: 'task_center_pool_busy' }, 'submissions.error.unavailable'],
  [422, { detail: '<html>invalid</html>' }, 'submissions.error.invalid'],
])('keeps HTTP %s and machine code while mapping to an actionable message', async (status, body, key) => {
  transport.mockResolvedValue(new Response(JSON.stringify(body), { status: Number(status) }));
  const error = await getSubmission('id', 'ws').catch(e => e);
  expect(error).toBeInstanceOf(SubmissionApiError);
  expect(error.status).toBe(status);
  expect(error.code).toBe('code' in body ? body.code : 'http_error');
  expect(submissionErrorKey(error)).toBe(key);
  expect(error.message).not.toContain('<html>');
});

it('retains cancellation instead of turning it into a visible network failure', async () => {
  const aborted = new DOMException('aborted', 'AbortError');
  transport.mockRejectedValue(aborted);
  await expect(getSubmission('id', 'ws')).rejects.toBe(aborted);
});
it('sanitizes network errors and invalid JSON without leaking upstream content', async () => {
  transport.mockRejectedValueOnce(new TypeError('secret upstream details'));
  const error = await getSubmission('id', 'ws').catch(e => e);
  expect(error).toMatchObject({ status: 0, code: 'connection_error' });
  expect(submissionErrorKey(error)).toBe('submissions.error.connection');
  transport.mockResolvedValueOnce(new Response('<html>private</html>'));
  await expect(getSubmission('id', 'ws')).rejects.toMatchObject({ status: 0, code: 'connection_error' });
});
