import { create } from 'zustand';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CrawlJob {
  id: string;
  run_id: string | null;
  url: string;
  competitor: string | null;
  dimension: string | null;
  status: string;  // pending | running | completed | failed
  attempt_count: number;
  error: string | null;
  created_at: string;
  updated_at: string;
}

interface CrawlState {
  jobs: CrawlJob[];
  loading: boolean;
  error: string | null;
  pollingIntervalId: any;
  fetchJobs: () => Promise<void>;
  createJob: (url: string, opts?: { competitor?: string; dimension?: string }) => Promise<void>;
  deleteJob: (id: string) => Promise<void>;
  retryJob: (id: string) => Promise<void>;
  bulkCreateJobs: (urls: string[], opts?: { competitor?: string; dimension?: string }) => Promise<void>;
  startPolling: () => void;
  stopPolling: () => void;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useCrawlStore = create<CrawlState>((set, get) => ({
  jobs: [],
  loading: false,
  error: null,
  pollingIntervalId: null,

  fetchJobs: async () => {
    set({ loading: true, error: null });
    try {
      const res = await fetch('/api/crawl/jobs');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      set({ jobs: data, loading: false });

      // Auto-start polling after fetchJobs if running jobs exist
      const hasRunning = data.some((job: CrawlJob) => job.status === 'pending' || job.status === 'running');
      if (hasRunning) {
        get().startPolling();
      } else {
        get().stopPolling();
      }
    } catch (err) {
      set({ error: String(err), loading: false });
    }
  },

  createJob: async (url, opts = {}) => {
    try {
      const res = await fetch('/api/crawl/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, ...opts }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const job = await res.json();
      set((s) => ({ jobs: [job, ...s.jobs] }));
    } catch (err) {
      set({ error: String(err) });
    }
  },

  deleteJob: async (id) => {
    try {
      const res = await fetch(`/api/crawl/jobs/${id}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      set((s) => ({ jobs: s.jobs.filter((j) => j.id !== id) }));
    } catch (err) {
      set({ error: String(err) });
    }
  },

  retryJob: async (id) => {
    const job = get().jobs.find((j) => j.id === id);
    if (!job) return;
    const opts: { competitor?: string; dimension?: string } = {};
    if (job.competitor !== null) opts.competitor = job.competitor;
    if (job.dimension !== null) opts.dimension = job.dimension;
    await get().createJob(job.url, opts);
  },

  bulkCreateJobs: async (urls, opts) => {
    await Promise.all(urls.map((url) => get().createJob(url, opts)));
  },

  startPolling: () => {
    if (get().pollingIntervalId) return;

    const intervalId = setInterval(async () => {
      const hasRunning = get().jobs.some((job) => job.status === 'pending' || job.status === 'running');
      if (hasRunning) {
        await get().fetchJobs();
      } else {
        get().stopPolling();
      }
    }, 3000);

    set({ pollingIntervalId: intervalId });
  },

  stopPolling: () => {
    const { pollingIntervalId } = get();
    if (pollingIntervalId) {
      clearInterval(pollingIntervalId);
      set({ pollingIntervalId: null });
    }
  },
}));

