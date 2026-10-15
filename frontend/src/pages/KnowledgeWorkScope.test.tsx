import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import SearchPage from './SearchPage';
import CrawlPage from './CrawlPage';
import { useSearchStore } from '../stores/searchStore';
import { useCrawlStore } from '../stores/crawlStore';
import { useI18n } from '../stores/i18n';

const response = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
const projects = [{ id: 'p-a', workspace_id: 'ws', name: '项目甲' }, { id: 'p-b', workspace_id: 'ws', name: '项目乙' }, { id: 'foreign', workspace_id: 'other', name: '其他工作区' }];
let navigate!: ReturnType<typeof useNavigate>;
function Host({ crawl = false }) { navigate = useNavigate(); const l = useLocation(); return <><output>{l.search}</output>{crawl ? <CrawlPage /> : <SearchPage />}</>; }
function setup(handler?: (url: string, init?: RequestInit) => Promise<Response> | undefined) {
  const fetcher = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === '/api/enterprise/workspaces') return Promise.resolve(response([{ id: 'ws' }]));
    if (url === '/api/enterprise/projects') return Promise.resolve(response(projects));
    return handler?.(url, init) ?? Promise.resolve(response(url.includes('/search') ? { hits: [] } : []));
  });
  vi.stubGlobal('fetch', fetcher); return fetcher;
}
beforeEach(() => { localStorage.setItem('competiscope.authToken', 'test-token'); useI18n.getState().setLocale('zh-CN'); useSearchStore.setState({ query: '', searchHistory: [] }); });
afterEach(() => { useCrawlStore.getState().stopPolling(); localStorage.clear(); sessionStorage.clear(); vi.unstubAllGlobals(); });

describe('knowledge work project scope', () => {
  it('sends the URL project and library flag through search and evaluation and rejects late results', async () => {
    let finishOld!: (value: Response) => void;
    const fetcher = setup((url) => url === '/api/knowledge/search' ? new Promise(resolve => { finishOld = resolve; }) : undefined);
    render(<MemoryRouter initialEntries={['/search?project_id=p-a&include_workspace_library=true']}><Host /></MemoryRouter>);
    await screen.findByRole('option', { name: '项目甲' });
    expect(screen.queryByRole('option', { name: '其他工作区' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText('搜索知识库...'), { target: { value: '旧查询' } });
    fireEvent.click(screen.getByRole('button', { name: '搜索' }));
    await waitFor(() => expect(finishOld).toBeDefined());
    const call = fetcher.mock.calls.find(([url]) => url === '/api/knowledge/search')!;
    expect(JSON.parse(String(call[1]?.body))).toMatchObject({ project_id: 'p-a', include_workspace_library: true });
    expect(fetcher.mock.calls.some(([url]) => String(url).includes('/eval/runs?project_id=p-a&include_workspace_library=true'))).toBe(true);
    act(() => navigate('/search?project_id=p-b'));
    await waitFor(() => expect(screen.getByLabelText('项目范围')).toHaveValue('p-b'));
    await act(async () => finishOld(response({ hits: [{ chunk_id: 'old', document_id: 'old', text: '旧范围结果', source_type: 'manual' }] })));
    expect(screen.queryByText('旧范围结果')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '旧查询' })).not.toBeInTheDocument();
  });

  it('does not issue broad requests before project loading or after an invalid explicit URL project', async () => {
    const fetcher = setup();
    render(<MemoryRouter initialEntries={['/search?project_id=foreign']}><Host /></MemoryRouter>);
    expect(screen.getByRole('button', { name: '搜索' })).toBeDisabled();
    expect(await screen.findByText('项目不存在或不属于当前工作区，请重新选择。')).toBeInTheDocument();
    expect(fetcher.mock.calls.some(([url]) => String(url).includes('/api/knowledge/'))).toBe(false);
  });

  it('limits unscoped local development to default-workspace projects', async () => {
    localStorage.clear(); setup();
    render(<MemoryRouter><Host /></MemoryRouter>);
    await screen.findByLabelText('项目范围');
    await waitFor(() => expect(screen.getByRole('button', { name: '搜索' })).not.toBeDisabled());
    expect(screen.queryByRole('option', { name: '项目甲' })).not.toBeInTheDocument();
  });

  it('scopes crawl creation, source progress and retry, leaves inherited library entries read only, and clears late source responses', async () => {
    let finishOld!: (value: Response) => void;
    const source = (id: string, projectId: string | null) => ({ id, project_id: projectId, workspace_id: 'ws', type: 'manual', config: { url: 'https://'+id+'.example', urls: ['https://'+id+'.example'] }, created_at: '2026-10-01' });
    const fetcher = setup((url, init) => {
      if (url.startsWith('/api/crawl/sources?') && init?.method === 'POST') return Promise.resolve(response({ source: source('new', 'p-a'), progress: {} }));
      if (url.startsWith('/api/crawl/sources?') && url.includes('p-b')) return new Promise(resolve => { finishOld = resolve; });
      if (url.startsWith('/api/crawl/sources?')) return Promise.resolve(response([source('own', 'p-a'), source('public', null)]));
      if (url.startsWith('/api/crawl/sources/')) return Promise.resolve(response({ source: source(url.includes('/public') ? 'public' : 'own', url.includes('/public') ? null : 'p-a'), progress: { failed: 1 } }));
      return undefined;
    });
    render(<MemoryRouter initialEntries={['/crawl?project_id=p-a&include_workspace_library=true']}><Host crawl /></MemoryRouter>);
    await screen.findByText('公共库条目只读');
    expect(fetcher.mock.calls.some(([url]) => url === '/api/crawl/sources/public?project_id=p-a&include_workspace_library=true')).toBe(true);
    fireEvent.change(screen.getByLabelText('URL 列表'), { target: { value: 'https://new.example' } });
    fireEvent.click(screen.getByRole('button', { name: '提交 URL 列表' }));
    await waitFor(() => expect(fetcher.mock.calls.some(([url, init]) => String(url).includes('/sources?project_id=p-a') && init?.method === 'POST')).toBe(true));
    const publicRow = screen.getAllByText('https://public.example')[0].closest('tr')!;
    expect(within(publicRow).getByRole('button', { name: '重试' })).toBeDisabled();
    const ownRow = screen.getAllByText('https://own.example')[0].closest('tr')!;
    fireEvent.click(within(ownRow).getByRole('button', { name: '重试' }));
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url === '/api/crawl/sources/own/retry?project_id=p-a&include_workspace_library=false')).toBe(true));
    act(() => navigate('/crawl?project_id=p-b')); await waitFor(() => expect(finishOld).toBeDefined());
    act(() => navigate('/crawl?project_id=p-a'));
    await act(async () => finishOld(response([source('late', 'p-b')])));
    expect(screen.queryByText('https://late.example')).not.toBeInTheDocument();
  });
});

it('sends evaluation scope and prevents old eval results from returning after an A to B to A switch', async () => {
  let finish!: (value: Response) => void;
  const fetcher = setup((url) => url === '/api/knowledge/eval' ? new Promise(resolve => { finish = resolve; }) : undefined);
  const { container } = render(<MemoryRouter initialEntries={['/search?project_id=p-a&include_workspace_library=true']}><Host /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole('button', { name: '搜索' })).not.toBeDisabled());
  const input = container.querySelector('input[type=file]')!;
  fireEvent.change(input, { target: { files: [new File(['{"query":"问题","relevant_doc_ids":["doc"]}'], 'labels.jsonl')] } });
  const button = screen.getByRole('button', { name: '运行评估' });
  await waitFor(() => expect(button).not.toBeDisabled()); fireEvent.click(button);
  await waitFor(() => expect(finish).toBeDefined());
  const call = fetcher.mock.calls.find(([url]) => url === '/api/knowledge/eval')!;
  expect(JSON.parse(String(call[1]?.body))).toMatchObject({ project_id: 'p-a', include_workspace_library: true });
  act(() => navigate('/search?project_id=p-b'));
  await waitFor(() => expect(screen.getByLabelText('项目范围')).toHaveValue('p-b'));
  act(() => navigate('/search?project_id=p-a&include_workspace_library=true'));
  await act(async () => finish(response({ id: 'late-eval', metrics: { mrr: 0.777 }, created_at: '2026-10-01', top_k: 5 })));
  expect(screen.queryByText('0.777')).not.toBeInTheDocument();
});

it('does not show late source progress from a previous crawl scope', async () => {
  let finish!: (value: Response) => void;
  setup((url) => {
    if (url === '/api/crawl/sources?project_id=p-a&include_workspace_library=false') return Promise.resolve(response([{ id: 'slow', project_id: 'p-a', type: 'rss', config: { url: 'https://slow.example' } }]));
    if (url.includes('/api/crawl/sources/slow?')) return new Promise(resolve => { finish = resolve; });
    return undefined;
  });
  render(<MemoryRouter initialEntries={['/crawl?project_id=p-a']}><Host crawl /></MemoryRouter>);
  await waitFor(() => expect(finish).toBeDefined());
  act(() => navigate('/crawl?project_id=p-b'));
  await act(async () => finish(response({ source: { id: 'slow', project_id: 'p-a', type: 'rss', config: { url: 'https://slow.example' } }, progress: { failed: 42 } })));
  expect(screen.queryByText('https://slow.example')).not.toBeInTheDocument();
});
