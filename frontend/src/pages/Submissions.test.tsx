import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BusinessRoutes } from '../features/desktop/apps';
import { Desktop } from '../features/desktop/Desktop';
import { useDesktopStore } from '../features/desktop/windowStore';
import { useI18n } from '../stores/i18n';
import type { QuotaLedgerPage, SubmissionView } from '../api/types';

function submission(overrides: Partial<SubmissionView> = {}): SubmissionView {
  return { id: 'sub-1', workspace_id: 'default-workspace', project_id: null, status: 'pending', expected_run_id: 'future-run',
    run_id: null, workflow_id: null, created_at: '2026-10-01T01:00:00Z', updated_at: '2026-10-01T01:00:00Z',
    period_start: '2026-10-01T00:00:00Z', dispatch_attempt_count: 0, last_error_code: null, run_status: null,
    run_status_observed_at: null, ...overrides };
}
function quota(overrides: Partial<QuotaLedgerPage['snapshot']> = {}): QuotaLedgerPage {
  return { items: [{ id: 'entry-1', workspace_id: 'default-workspace', submission_id: 'sub-1', action: 'reserve', amount: 1,
    period_start: '2026-10-01T00:00:00Z', created_at: '2026-10-01T01:00:00Z' }], next_cursor: null,
    snapshot: { workspace_id: 'default-workspace', period_start: '2026-10-01T00:00:00Z', period_end: '2026-11-01T00:00:00Z',
      limit: 10, enforcement: 'block', imported_count: 3, reserved_count: 4, available: 3, ...overrides } };
}
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
let route: (url: URL, init?: RequestInit) => Response | Promise<Response>;
const transport = vi.fn((path: string, init?: RequestInit) => route(new URL(path, 'http://localhost'), init));
function baseRoute(url: URL) {
  if (url.pathname === '/api/runtime') return json({ task_center_enabled: true, default_execution_mode: 'demo' });
  if (url.pathname === '/api/task-submissions') return json({ items: [submission()], next_cursor: null });
  if (url.pathname.includes('/quota-ledger')) return json(quota());
  if (url.pathname.startsWith('/api/task-submissions/')) return json(submission());
  return json([]);
}
function Navigation() { const go = useNavigate(); return <button onClick={() => go('/submissions/sub-2?workspace_id=other')}>测试切换详情</button>; }
function open(path = '/submissions', navigation = false) {
  return render(<MemoryRouter initialEntries={[path]} future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
    {navigation ? <Navigation /> : null}<BusinessRoutes />
  </MemoryRouter>);
}
const callsFor = (pathname: string) => transport.mock.calls.filter(([path]) => new URL(path, 'http://localhost').pathname === pathname);

beforeEach(() => {
  useI18n.getState().setLocale('zh-CN');
  localStorage.removeItem('competiscope.workspaceId');
  route = baseRoute;
  transport.mockClear();
  vi.stubGlobal('fetch', transport);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('submission list and authoritative quota', () => {
  it('loads current workspace, filters, uses server cursors, resets to first page, and refreshes', async () => {
    route = (url) => url.pathname === '/api/task-submissions'
      ? json({ items: [submission({ id: url.searchParams.get('cursor') ? 'sub-page-2' : 'sub-1' })], next_cursor: url.searchParams.get('cursor') ? null : 'next+/=' }) : baseRoute(url);
    open();
    expect(await screen.findByRole('heading', { name: '提交中心' })).toBeInTheDocument();
    await screen.findByRole('link', { name: 'sub-1' });
    expect(new URL(callsFor('/api/task-submissions')[0][0], 'http://localhost').searchParams.get('workspace_id')).toBe('default-workspace');
    await userEvent.selectOptions(screen.getByLabelText('提交状态'), 'dispatch_failed');
    await waitFor(() => expect(new URL(callsFor('/api/task-submissions').slice(-1)[0][0], 'http://localhost').searchParams.get('status')).toBe('dispatch_failed'));
    await userEvent.click(screen.getByRole('button', { name: '下一页提交' }));
    await screen.findByRole('link', { name: 'sub-page-2' });
    expect(new URL(callsFor('/api/task-submissions').slice(-1)[0][0], 'http://localhost').searchParams.get('cursor')).toBe('next+/=');
    await userEvent.click(screen.getByRole('button', { name: '回到提交首页' }));
    await screen.findByRole('link', { name: 'sub-1' });
    const before = callsFor('/api/task-submissions').length;
    await userEvent.click(screen.getByRole('button', { name: '刷新提交' }));
    await waitFor(() => expect(callsFor('/api/task-submissions').length).toBe(before + 1));
  });

  it('shows empty results and explicit disabled service without task requests', async () => {
    route = url => url.pathname === '/api/task-submissions' ? json({ items: [], next_cursor: null }) : baseRoute(url);
    const mounted = open();
    expect(await screen.findByText('当前筛选下没有提交。')).toBeInTheDocument();
    mounted.unmount(); transport.mockClear();
    route = url => url.pathname === '/api/runtime' ? json({ task_center_enabled: false }) : baseRoute(url);
    open();
    expect(await screen.findByText(/提交中心尚未启用/)).toBeInTheDocument();
    expect(callsFor('/api/task-submissions')).toHaveLength(0);
    expect(transport.mock.calls.filter(([path]) => path.includes('quota-ledger'))).toHaveLength(0);
  });

  it.each([403, 503])('localizes a list HTTP %s without exposing HTML and recovers on manual refresh', async status => {
    route = url => url.pathname === '/api/task-submissions' ? new Response('<html>private upstream error</html>', { status }) : baseRoute(url);
    open();
    const error = await screen.findByRole('alert');
    expect(error).toHaveTextContent(status === 403 ? /权限/ : /暂时不可用/);
    expect(error).not.toHaveTextContent('private upstream');
    route = baseRoute;
    await userEvent.click(screen.getByRole('button', { name: '刷新提交' }));
    expect(await screen.findByRole('link', { name: 'sub-1' })).toBeInTheDocument();
  });

  it('uses whole-month snapshot rather than summing the current ledger page, including true zero and monitor allowance', async () => {
    route = url => url.pathname.includes('/quota-ledger')
      ? json({ ...quota({ limit: 0, enforcement: 'monitor', imported_count: 9, reserved_count: 8, available: 0 }),
        items: [ { ...quota().items[0], id: url.searchParams.get('cursor') ? 'entry-2' : 'entry-1', action: url.searchParams.get('cursor') ? 'release' : 'reserve' } ],
        next_cursor: url.searchParams.get('cursor') ? null : 'ledger-next' }) : baseRoute(url);
    open();
    const region = await screen.findByRole('region', { name: '研究次数额度' });
    await within(region).findByText('entry-1');
    expect(within(region).getByLabelText('上限')).toHaveTextContent('0');
    expect(within(region).getByLabelText('历史导入')).toHaveTextContent('9');
    expect(within(region).getByLabelText('当前预占')).toHaveTextContent('8');
    expect(within(region).getByText(/监测模式.*继续/)).toBeInTheDocument();
    expect(within(region).getByText(/次数.*模型账单/)).toBeInTheDocument();
    expect(within(region).getByText(/2026-10-01.*2026-11-01.*UTC/)).toBeInTheDocument();
    await userEvent.click(within(region).getByRole('button', { name: '下一页流水' }));
    await within(region).findByText('entry-2');
    expect(within(region).getByText('释放')).toBeInTheDocument();
    expect(within(region).getByLabelText('当前预占')).toHaveTextContent('8');
    await userEvent.click(within(region).getByRole('button', { name: '回到流水首页' }));
    await within(region).findByText('entry-1');
    fireEvent.change(screen.getByLabelText('额度月份（UTC）'), { target: { value: '2026-09' } });
    await waitFor(() => expect(new URL(transport.mock.calls.filter(([path]) => path.includes('quota-ledger')).slice(-1)[0][0], 'http://localhost').searchParams.get('period_start')).toBe('2026-09-01T00:00:00Z'));
    expect(new URL(transport.mock.calls.filter(([path]) => path.includes('quota-ledger')).slice(-1)[0][0], 'http://localhost').searchParams.has('cursor')).toBe(false);
  });

  it('isolates quota permission failure and never shows an invented zero', async () => {
    route = url => url.pathname.includes('/quota-ledger') ? json({ code: 'denied' }, 403) : baseRoute(url);
    open();
    await screen.findByRole('link', { name: 'sub-1' });
    const region = screen.getByRole('region', { name: '研究次数额度' });
    expect(await within(region).findByRole('alert')).toHaveTextContent('权限');
    expect(within(region).queryByLabelText('剩余次数')).not.toBeInTheDocument();
  });

  it('drops old workspace responses and resets cursor without retaining another workspace balance', async () => {
    let resolveOld!: (r: Response) => void;
    let oldSignal: AbortSignal | null | undefined;
    route = (url, init) => {
      if (url.pathname === '/api/task-submissions' && url.searchParams.get('workspace_id') === 'default-workspace') {
        oldSignal = init?.signal;
        return new Promise(r => { resolveOld = r; });
      }
      if (url.pathname === '/api/task-submissions') return json({ items: [submission({ id: 'other-sub', workspace_id: 'other' })] });
      if (url.pathname.includes('/quota-ledger')) return json(quota({ workspace_id: url.pathname.includes('/other/') ? 'other' : 'default-workspace', available: url.pathname.includes('/other/') ? 7 : 3 }));
      return baseRoute(url);
    };
    open();
    await waitFor(() => expect(resolveOld).toBeTypeOf('function'));
    await userEvent.clear(screen.getByLabelText('工作空间'));
    await userEvent.type(screen.getByLabelText('工作空间'), 'other');
    await userEvent.click(screen.getByRole('button', { name: '切换工作空间' }));
    await screen.findByRole('link', { name: 'other-sub' });
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => { resolveOld(json({ items: [submission({ id: 'stale-sub' })] })); });
    expect(screen.queryByRole('link', { name: 'stale-sub' })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText('剩余次数')).toHaveTextContent('7'));
  });
});

describe('submission detail mutation and lifecycle', () => {
  it('shows dispatch separately from observed run status and links only the actual run', async () => {
    route = url => url.pathname === '/api/task-submissions/sub-1' ? json(submission({ status: 'dispatched', run_id: 'actual/run', run_status: 'failed', run_status_observed_at: '2026-10-02T00:00:00Z', dispatch_attempt_count: 2 })) : baseRoute(url);
    open('/submissions/sub-1');
    await screen.findByRole('heading', { name: '提交详情' });
    expect(await screen.findByText('运行失败')).toBeInTheDocument();
    expect(screen.getByText('已派发')).toBeInTheDocument();
    expect(screen.getByText(/2026-10-02/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '打开研究运行' })).toHaveAttribute('href', '/runs/actual%2Frun?view=report');
    expect(screen.queryByRole('button', { name: '重试派发' })).not.toBeInTheDocument();
    expect(screen.queryByText(/报告已完成|报告合格/)).not.toBeInTheDocument();
  });

  it('does not make expected_run_id into a fake result link', async () => {
    open('/submissions/sub-1');
    await screen.findByText('future-run');
    expect(screen.queryByRole('link', { name: '打开研究运行' })).not.toBeInTheDocument();
    expect(screen.getByText(/演示资料/)).toBeInTheDocument();
  });

  it('handles cancel 409 by refreshing actual state without announcing success', async () => {
    let cancelled = false;
    route = (url, init) => {
      if (url.pathname.endsWith('/cancel') && init?.method === 'POST') { cancelled = true; return json({ code: 'dispatch_conflict' }, 409); }
      if (url.pathname === '/api/task-submissions/sub-1') return json(submission({ status: cancelled ? 'dispatching' : 'pending' }));
      return baseRoute(url);
    };
    open('/submissions/sub-1');
    await userEvent.click(await screen.findByRole('button', { name: '取消提交' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/状态已变化/);
    expect(await screen.findByText('正在派发')).toBeInTheDocument();
    expect(screen.queryByText('已取消')).not.toBeInTheDocument();
    expect(callsFor('/api/task-submissions/sub-1/cancel')).toHaveLength(1);
  });

  it('cancels only after the server confirms and prevents duplicate mutation', async () => {
    let resolveCancel!: (r: Response) => void;
    route = (url, init) => url.pathname.endsWith('/cancel') && init?.method === 'POST'
      ? new Promise(r => { resolveCancel = r; }) : baseRoute(url);
    open('/submissions/sub-1');
    const button = await screen.findByRole('button', { name: '取消提交' });
    await userEvent.dblClick(button);
    expect(callsFor('/api/task-submissions/sub-1/cancel')).toHaveLength(1);
    expect(screen.queryByText('已取消')).not.toBeInTheDocument();
    await act(async () => { resolveCancel(json(submission({ status: 'cancelled' }))); });
    expect(await screen.findByText('已取消')).toBeInTheDocument();
  });

  it.each([202, 503])('retries failed dispatch through the existing submission and handles HTTP %s', async status => {
    route = (url, init) => {
      if (url.pathname.endsWith('/retry-dispatch') && init?.method === 'POST') return status === 202 ? json(submission({ status: 'pending', dispatch_attempt_count: 3 }), status) : json({ code: 'task_center_unavailable' }, status);
      if (url.pathname === '/api/task-submissions/sub-1') return json(submission({ status: 'dispatch_failed', dispatch_attempt_count: 2, last_error_code: 'attempts_exhausted' }));
      return baseRoute(url);
    };
    open('/submissions/sub-1');
    await userEvent.click(await screen.findByRole('button', { name: '重试派发' }));
    expect(callsFor('/api/task-submissions/sub-1/retry-dispatch')).toHaveLength(1);
    if (status === 202) expect(await screen.findByText('待派发')).toBeInTheDocument();
    else expect(await screen.findByRole('alert')).toHaveTextContent(/暂时不可用/);
    expect(callsFor('/api/task-submissions')).toHaveLength(0);
  });

  it('shows localized not-found and can recover after refreshing', async () => {
    route = url => url.pathname === '/api/task-submissions/sub-1' ? json({ code: 'submission_not_found' }, 404) : baseRoute(url);
    open('/submissions/sub-1');
    expect(await screen.findByRole('alert')).toHaveTextContent(/找不到此提交/);
    route = baseRoute;
    await userEvent.click(screen.getByRole('button', { name: '刷新详情' }));
    expect(await screen.findByText('future-run')).toBeInTheDocument();
  });

  it('aborts and discards an old detail response after id/workspace navigation', async () => {
    let resolveOld!: (r: Response) => void;
    let oldSignal: AbortSignal | null | undefined;
    route = (url, init) => {
      if (url.pathname === '/api/task-submissions/sub-1') { oldSignal = init?.signal; return new Promise(r => { resolveOld = r; }); }
      if (url.pathname === '/api/task-submissions/sub-2') return json(submission({ id: 'sub-2', workspace_id: 'other', expected_run_id: 'new-run' }));
      return baseRoute(url);
    };
    open('/submissions/sub-1', true);
    await waitFor(() => expect(resolveOld).toBeTypeOf('function'));
    await userEvent.click(screen.getByRole('button', { name: '测试切换详情' }));
    await screen.findByText('new-run');
    await act(async () => { resolveOld(json(submission({ expected_run_id: 'stale-run' }))); });
    expect(oldSignal?.aborted).toBe(true);
    expect(screen.queryByText('stale-run')).not.toBeInTheDocument();
  });

  it('polls without overlap, stops while hidden/unmounted, and stops on terminal state', async () => {
    let resolvePoll!: (r: Response) => void;
    let reads = 0;
    route = url => {
      if (url.pathname === '/api/task-submissions/sub-1') {
        reads += 1;
        if (reads === 2) return new Promise(r => { resolvePoll = r; });
        return json(submission());
      }
      return baseRoute(url);
    };
    vi.useFakeTimers();
    const mounted = open('/submissions/sub-1');
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText('future-run')).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(reads).toBe(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(12000); });
    expect(reads).toBe(2);
    await act(async () => { resolvePoll(json(submission({ status: 'dispatched', run_id: 'run-1', run_status: 'completed' }))); });
    await act(async () => { await vi.advanceTimersByTimeAsync(16000); });
    expect(reads).toBe(2);
    mounted.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
    expect(reads).toBe(2);
  });

  it('pauses hidden polling and resumes with one request on visibility restore, then stops after failure', async () => {
    vi.useFakeTimers();
    open('/submissions/sub-1');
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText('future-run')).toBeInTheDocument();
    act(() => { Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' }); document.dispatchEvent(new Event('visibilitychange')); });
    const before = callsFor('/api/task-submissions/sub-1').length;
    await act(async () => { await vi.advanceTimersByTimeAsync(16000); });
    expect(callsFor('/api/task-submissions/sub-1').length).toBe(before);
    route = url => url.pathname === '/api/task-submissions/sub-1' ? Promise.reject(new TypeError('offline details')) : baseRoute(url);
    await act(async () => { Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' }); document.dispatchEvent(new Event('visibilitychange')); });
    expect(screen.getByRole('alert')).toHaveTextContent(/连接/);
    const failed = callsFor('/api/task-submissions/sub-1').length;
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(callsFor('/api/task-submissions/sub-1').length).toBe(failed);
  });
});


it('aborts an active in-flight read on unmount and ignores late completion', async () => {
  let resolvePending!: (r: Response) => void;
  let pendingSignal: AbortSignal | null | undefined;
  route = (url, init) => {
    if (url.pathname === '/api/task-submissions/sub-1') { pendingSignal = init?.signal; return new Promise(r => { resolvePending = r; }); }
    return baseRoute(url);
  };
  const mounted = open('/submissions/sub-1');
  await waitFor(() => expect(resolvePending).toBeTypeOf('function'));
  vi.useFakeTimers();
  mounted.unmount();
  expect(pendingSignal?.aborted).toBe(true);
  const before = callsFor('/api/task-submissions/sub-1').length;
  await act(async () => { resolvePending(json(submission())); await vi.advanceTimersByTimeAsync(20000); });
  expect(callsFor('/api/task-submissions/sub-1').length).toBe(before);
});

it('aborts a hidden in-flight request, discards its response and does not poll until visible', async () => {
  let resolvePending!: (r: Response) => void;
  let pendingSignal: AbortSignal | null | undefined;
  route = (url, init) => {
    if (url.pathname === '/api/task-submissions/sub-1') { pendingSignal = init?.signal; return new Promise(r => { resolvePending = r; }); }
    return baseRoute(url);
  };
  open('/submissions/sub-1');
  await waitFor(() => expect(resolvePending).toBeTypeOf('function'));
  vi.useFakeTimers();
  act(() => { Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' }); document.dispatchEvent(new Event('visibilitychange')); });
  expect(pendingSignal?.aborted).toBe(true);
  await act(async () => { resolvePending(json(submission({ expected_run_id: 'hidden-result' }))); await vi.advanceTimersByTimeAsync(20000); });
  expect(screen.queryByText('hidden-result')).not.toBeInTheDocument();
  expect(callsFor('/api/task-submissions/sub-1')).toHaveLength(1);
});

it('does not restart terminal polling when document visibility changes', async () => {
  route = url => url.pathname === '/api/task-submissions/sub-1' ? json(submission({ status: 'cancelled' })) : baseRoute(url);
  open('/submissions/sub-1');
  await screen.findByText('已取消');
  const before = callsFor('/api/task-submissions/sub-1').length;
  act(() => { Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' }); document.dispatchEvent(new Event('visibilitychange')); });
  act(() => { Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' }); document.dispatchEvent(new Event('visibilitychange')); });
  await act(async () => { await Promise.resolve(); });
  expect(callsFor('/api/task-submissions/sub-1').length).toBe(before);
});

it('discards responses from the previous status filter', async () => {
  let resolveOld!: (r: Response) => void;
  let oldSignal: AbortSignal | null | undefined;
  route = (url, init) => {
    if (url.pathname === '/api/task-submissions' && !url.searchParams.has('status')) { oldSignal = init?.signal; return new Promise(r => { resolveOld = r; }); }
    if (url.pathname === '/api/task-submissions') return json({ items: [submission({ id: 'filtered', status: 'cancelled' })] });
    return baseRoute(url);
  };
  open();
  await waitFor(() => expect(resolveOld).toBeTypeOf('function'));
  await userEvent.selectOptions(screen.getByLabelText('提交状态'), 'cancelled');
  await screen.findByRole('link', { name: 'filtered' });
  await act(async () => { resolveOld(json({ items: [submission({ id: 'old-filter' })] })); });
  expect(oldSignal?.aborted).toBe(true);
  expect(screen.queryByRole('link', { name: 'old-filter' })).not.toBeInTheDocument();
});

it('does not retain another workspace quota while the new scope is denied', async () => {
  route = url => url.pathname.includes('/other/quota-ledger') ? json({ code: 'denied' }, 403) : baseRoute(url);
  open();
  await screen.findByLabelText('剩余次数');
  await userEvent.clear(screen.getByLabelText('工作空间'));
  await userEvent.type(screen.getByLabelText('工作空间'), 'other');
  await userEvent.click(screen.getByRole('button', { name: '切换工作空间' }));
  const region = screen.getByRole('region', { name: '研究次数额度' });
  expect(await within(region).findByRole('alert')).toHaveTextContent('权限');
  expect(within(region).queryByLabelText('剩余次数')).not.toBeInTheDocument();
});

it('aborts an old mutation and ignores its response after detail navigation', async () => {
  let resolveCancel!: (r: Response) => void;
  let mutationSignal: AbortSignal | null | undefined;
  route = (url, init) => {
    if (url.pathname.endsWith('/cancel')) { mutationSignal = init?.signal; return new Promise(r => { resolveCancel = r; }); }
    if (url.pathname === '/api/task-submissions/sub-2') return json(submission({ id: 'sub-2', expected_run_id: 'new-detail' }));
    return baseRoute(url);
  };
  open('/submissions/sub-1', true);
  await userEvent.click(await screen.findByRole('button', { name: '取消提交' }));
  await userEvent.click(screen.getByRole('button', { name: '测试切换详情' }));
  await screen.findByText('new-detail');
  await act(async () => { resolveCancel(json(submission({ status: 'cancelled' }))); });
  expect(mutationSignal?.aborted).toBe(true);
  expect(screen.queryByText('已取消')).not.toBeInTheDocument();
});


describe('workspace-preserving new research entry', () => {
  it.each([
    { start: '/submissions?workspace_id=selected-space', identity: 'identity-space', expected: 'selected-space', entry: true },
    { start: '/', identity: 'identity-space', expected: 'identity-space', entry: false },
  ])('creates and reads the submission in $expected', async ({ start, identity, expected, entry }) => {
    localStorage.setItem('competiscope.workspaceId', identity);
    let createdWorkspace = '';
    route = (url, init) => {
      if (url.pathname === '/api/runtime') return json({ task_center_enabled: true, default_execution_mode: 'demo', has_web_search_key: false, auto_redo_warn_enabled: false });
      if (url.pathname.endsWith('/quota-decision')) return json({ allowed: true });
      if (url.pathname === '/api/skills') return json([{ name: 'pricing' }]);
      if (url.pathname === '/api/task-submissions' && init?.method === 'POST') {
        createdWorkspace = JSON.parse(String(init.body)).request.workspace_id;
        return json(submission({ workspace_id: createdWorkspace }), 202);
      }
      if (url.pathname === '/api/task-submissions/sub-1') return url.searchParams.get('workspace_id') === createdWorkspace
        ? json(submission({ workspace_id: createdWorkspace })) : json({ code: 'submission_not_found' }, 404);
      return baseRoute(url);
    };
    open(start);
    if (entry) {
      const link = await screen.findByRole('link', { name: '新建研究' });
      expect(link).toHaveAttribute('href', `/?workspace_id=${expected}`);
      await userEvent.click(link);
    }
    const target = await screen.findByLabelText('目标产品名称（必填）');
    fireEvent.change(target, { target: { value: '当前空间测试产品' } });
    await waitFor(() => expect(document.querySelector('[data-action-id="new-run.submit"]')).not.toBeDisabled());
    fireEvent.submit(target.closest('form')!);
    await screen.findByRole('heading', { name: '提交详情' });
    await screen.findByText('future-run');
    expect(createdWorkspace).toBe(expected);
    expect(new URL(callsFor('/api/task-submissions/sub-1')[0][0], 'http://localhost').searchParams.get('workspace_id')).toBe(expected);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByLabelText('工作空间')).toHaveValue(expected);
    expect(transport.mock.calls.some(([path]) => new URL(path, 'http://localhost').pathname === `/api/enterprise/workspaces/${expected}/quota-decision`)).toBe(true);
  });
});

describe('confirmed mutations refresh the same visible quota month', () => {
  it.each(['cancel', 'retry'] as const)('refetches the authoritative snapshot after confirmed %s', async kind => {
    let confirmed = false;
    let resolveMutation!: (r: Response) => void;
    route = (url, init) => {
      if (url.pathname.endsWith(kind === 'cancel' ? '/cancel' : '/retry-dispatch') && init?.method === 'POST') return new Promise(resolve => { resolveMutation = resolve; });
      if (url.pathname.includes('/quota-ledger')) return json(quota({ limit: 11, reserved_count: confirmed ? 2 : 1, available: confirmed ? 8 : 0 }));
      if (url.pathname === '/api/task-submissions/sub-1') return json(submission({ status: kind === 'cancel' ? 'pending' : 'dispatch_failed' }));
      return baseRoute(url);
    };
    open('/submissions/sub-1');
    const region = await screen.findByRole('region', { name: '研究次数额度' });
    await within(region).findByLabelText('剩余次数');
    fireEvent.change(screen.getByLabelText('额度月份（UTC）'), { target: { value: '2026-09' } });
    await waitFor(() => expect(transport.mock.calls.filter(([path]) => path.includes('/quota-ledger'))).toHaveLength(2));
    await waitFor(() => expect(within(region).getByLabelText('剩余次数')).toHaveTextContent('0'));
    await userEvent.click(await screen.findByRole('button', { name: kind === 'cancel' ? '取消提交' : '重试派发' }));
    expect(transport.mock.calls.filter(([path]) => path.includes('/quota-ledger'))).toHaveLength(2);
    confirmed = true;
    await act(async () => { resolveMutation(json(submission({ status: kind === 'cancel' ? 'cancelled' : 'pending' }), kind === 'cancel' ? 200 : 202)); });
    await waitFor(() => expect(within(region).getByLabelText('剩余次数')).toHaveTextContent('8'));
    expect(within(region).getByLabelText('当前预占')).toHaveTextContent('2');
    const ledgerReads = transport.mock.calls.filter(([path]) => path.includes('/quota-ledger'));
    expect(ledgerReads).toHaveLength(3);
    expect(new URL(ledgerReads[2][0], 'http://localhost').searchParams.get('period_start')).toBe('2026-09-01T00:00:00Z');
    expect(screen.getByLabelText('额度月份（UTC）')).toHaveValue('2026-09');
  });
});


describe('real desktop submission window visibility', () => {
  function openDesktopDetail() {
    useDesktopStore.setState({ windows: [], activeId: null });
    history.replaceState(null, '', '/submissions/sub-1?workspace_id=default-workspace');
    return render(<Desktop />);
  }
  const settle = async () => { await act(async () => { await Promise.resolve(); }); };

  it('stops scheduled polling while minimized, preserves the chosen month, and reloads on restore', async () => {
    vi.useFakeTimers();
    const { container } = openDesktopDetail();
    await settle();
    expect(screen.getByText('future-run')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('额度月份（UTC）'), { target: { value: '2026-09' } });
    await settle();
    const before = callsFor('/api/task-submissions/sub-1').length;
    const readsBefore = transport.mock.calls.filter(([path]) => path.startsWith('/api/task-submissions') || path.includes('/quota-ledger')).length;
    expect(before).toBe(1);
    fireEvent.click(screen.getByRole('button', { name: '最小化 提交中心' }));
    expect(container.querySelector('.desktop-window')).toHaveAttribute('hidden');
    expect(document.visibilityState).toBe('visible');
    await act(async () => { await vi.advanceTimersByTimeAsync(12000); });
    expect(callsFor('/api/task-submissions/sub-1')).toHaveLength(before);
    expect(transport.mock.calls.filter(([path]) => path.startsWith('/api/task-submissions') || path.includes('/quota-ledger'))).toHaveLength(readsBefore);
    fireEvent.click(screen.getByRole('button', { name: '恢复 提交中心' }));
    await settle();
    expect(container.querySelector('.desktop-window')).not.toHaveAttribute('hidden');
    expect(callsFor('/api/task-submissions/sub-1')).toHaveLength(before + 1);
    expect(screen.getByLabelText('额度月份（UTC）')).toHaveValue('2026-09');
    const quotaReads = transport.mock.calls.filter(([path]) => path.includes('/quota-ledger'));
    expect(new URL(quotaReads[quotaReads.length - 1][0], 'http://localhost').searchParams.get('period_start')).toBe('2026-09-01T00:00:00Z');
  });

  it('aborts an in-flight minimized poll, serializes the restored read, and discards late hidden results', async () => {
    let reads = 0;
    let oldSignal: AbortSignal | null | undefined;
    let restoredSignal: AbortSignal | null | undefined;
    let resolveOld!: (response: Response) => void;
    let resolveRestored!: (response: Response) => void;
    route = (url, init) => {
      if (url.pathname === '/api/task-submissions/sub-1') {
        reads += 1;
        if (reads === 2) { oldSignal = init?.signal; return new Promise(resolve => { resolveOld = resolve; }); }
        if (reads === 3) { restoredSignal = init?.signal; return new Promise(resolve => { resolveRestored = resolve; }); }
        return json(submission());
      }
      return baseRoute(url);
    };
    vi.useFakeTimers();
    openDesktopDetail();
    await settle();
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(reads).toBe(2);
    expect(oldSignal?.aborted).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '最小化 提交中心' }));
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(12000); });
    expect(reads).toBe(2);
    fireEvent.click(screen.getByRole('button', { name: '恢复 提交中心' }));
    await settle();
    expect(reads).toBe(3);
    expect(restoredSignal?.aborted).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(12000); });
    expect(reads).toBe(3);
    await act(async () => { resolveRestored(json(submission({ expected_run_id: 'restored-result', status: 'cancelled' }))); });
    expect(screen.getByText('restored-result')).toBeInTheDocument();
    await act(async () => { resolveOld(json(submission({ expected_run_id: 'old-hidden-result' }))); await vi.advanceTimersByTimeAsync(12000); });
    expect(screen.queryByText('old-hidden-result')).not.toBeInTheDocument();
    expect(screen.getByText('restored-result')).toBeInTheDocument();
    expect(screen.getByText('已取消')).toBeInTheDocument();
    expect(reads).toBe(3);
  });
});


it('retains a failed desktop resource across minimize/restore and recovers only on manual refresh', async () => {
  route = url => url.pathname === '/api/task-submissions/sub-1' ? json({ code: 'task_center_unavailable' }, 503) : baseRoute(url);
  useDesktopStore.setState({ windows: [], activeId: null });
  history.replaceState(null, '', '/submissions/sub-1?workspace_id=default-workspace');
  vi.useFakeTimers();
  render(<Desktop />);
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByRole('alert')).toHaveTextContent('暂时不可用');
  expect(callsFor('/api/task-submissions/sub-1')).toHaveLength(1);
  for (let count = 0; count < 2; count += 1) {
    fireEvent.click(screen.getByRole('button', { name: '最小化 提交中心' }));
    await act(async () => { await vi.advanceTimersByTimeAsync(12000); });
    fireEvent.click(screen.getByRole('button', { name: '恢复 提交中心' }));
    await act(async () => { await Promise.resolve(); await vi.advanceTimersByTimeAsync(12000); });
  }
  expect(callsFor('/api/task-submissions/sub-1')).toHaveLength(1);
  expect(screen.getByRole('alert')).toHaveTextContent('暂时不可用');
  route = baseRoute;
  fireEvent.click(screen.getByRole('button', { name: '刷新详情' }));
  await act(async () => { await Promise.resolve(); });
  expect(callsFor('/api/task-submissions/sub-1')).toHaveLength(2);
  expect(screen.getByText('future-run')).toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
  expect(callsFor('/api/task-submissions/sub-1')).toHaveLength(3);
});
