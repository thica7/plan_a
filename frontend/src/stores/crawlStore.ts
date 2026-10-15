import { apiFetch } from '../api/http';
import { create } from 'zustand';
import { knowledgeScopeUrl, type KnowledgeWorkScope } from '../features/knowledge/KnowledgeScopeControl';
import type { CrawlJob } from '../api/crawl';
export type { CrawlJob } from '../api/crawl';

interface CrawlState {
  jobs: CrawlJob[];
  scope: KnowledgeWorkScope | null;
  loading: boolean;
  error: string | null;
  pollingIntervalId: ReturnType<typeof setInterval> | null;
  setScope: (scope: KnowledgeWorkScope | null) => void;
  fetchJobs: () => Promise<void>;
  createJob: (url: string, opts?: { competitor?: string; dimension?: string }) => Promise<void>;
  deleteJob: (id: string) => Promise<void>;
  retryJob: (id: string) => Promise<void>;
  bulkCreateJobs: (urls: string[], opts?: { competitor?: string; dimension?: string }) => Promise<void>;
  startPolling: () => void;
  stopPolling: () => void;
}

let scopeGeneration = 0;
let jobsRequest = 0;
let controller: AbortController | null = null;

export const useCrawlStore = create<CrawlState>((set, get) => ({
  jobs: [], scope: null, loading: false, error: null, pollingIntervalId: null,
  setScope: scope => {
    scopeGeneration += 1; jobsRequest += 1; controller?.abort();
    get().stopPolling();
    set({ scope, jobs: [], loading: false, error: null });
  },
  fetchJobs: async () => {
    const scope = get().scope;
    if (!scope) return;
    const generation = scopeGeneration;
    const request = ++jobsRequest;
    controller?.abort(); controller = new AbortController();
    set({ loading: true, error: null });
    try {
      const res = await apiFetch(knowledgeScopeUrl('/api/crawl/jobs', scope), { signal: controller.signal });
      if (!res.ok) throw new Error(`任务读取失败（HTTP ${res.status}）`);
      const data: CrawlJob[] = await res.json();
      if (generation !== scopeGeneration || request !== jobsRequest) return;
      set({ jobs: data, loading: false });
      if (data.some(job => ['pending', 'running'].includes(job.status))) get().startPolling();
      else get().stopPolling();
    } catch (err) {
      if (generation !== scopeGeneration || request !== jobsRequest) return;
      set({ error: err instanceof Error ? err.message : String(err), loading: false });
    }
  },
  createJob: async (url, opts = {}) => {
    const scope = get().scope;
    if (!scope) return;
    const generation = scopeGeneration;
    try {
      const res = await apiFetch(knowledgeScopeUrl('/api/crawl/jobs', scope, true), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, ...opts, project_id: scope.projectId }),
      });
      if (!res.ok) throw new Error(`任务创建失败（HTTP ${res.status}）`);
      const job = await res.json();
      if (generation !== scopeGeneration) return;
      set(state => ({ jobs: [job, ...state.jobs] }));
      get().startPolling();
    } catch (err) {
      if (generation === scopeGeneration) set({ error: err instanceof Error ? err.message : String(err) });
    }
  },
  // The server currently exposes retries/deletion for sources, not individual jobs.
  deleteJob: async () => { set({ error: '尚未提供单任务删除，请在所属来源管理采集。' }); },
  retryJob: async () => { set({ error: '尚未提供单任务重试，请从所属来源重新采集。' }); },
  bulkCreateJobs: async (urls, opts) => {
    await Promise.all(urls.map(url => get().createJob(url, opts)));
  },
  startPolling: () => {
    if (get().pollingIntervalId || !get().scope) return;
    const generation = scopeGeneration;
    const interval = setInterval(() => {
      if (generation !== scopeGeneration) return;
      if (get().jobs.some(job => ['pending', 'running'].includes(job.status))) void get().fetchJobs();
      else get().stopPolling();
    }, 3000);
    set({ pollingIntervalId: interval });
  },
  stopPolling: () => {
    const interval = get().pollingIntervalId;
    if (interval) clearInterval(interval);
    set({ pollingIntervalId: null });
  },
}));
