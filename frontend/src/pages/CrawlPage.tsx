import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, RefreshCw, Sparkles } from 'lucide-react';
import { useCrawlStore } from '../stores/crawlStore';
import { ManualTab } from '../features/crawl/ManualTab';
import { SitemapTab } from '../features/crawl/SitemapTab';
import { RssTab } from '../features/crawl/RssTab';
import { JobQueueTable, type CrawlSource } from '../features/crawl/JobQueueTable';
import { FailedUrlsPanel } from '../features/crawl/FailedUrlsPanel';

type SourceTab = 'manual' | 'sitemap' | 'rss';

interface CrawlSourceDetail {
  source: CrawlSource;
  progress: Record<string, number>;
}

async function listSources(): Promise<CrawlSource[]> {
  const res = await fetch('/api/crawl/sources');
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<CrawlSource[]>;
}

async function getSourceDetail(sourceId: string): Promise<CrawlSourceDetail> {
  const res = await fetch(`/api/crawl/sources/${sourceId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<CrawlSourceDetail>;
}

async function retrySource(sourceId: string): Promise<void> {
  const res = await fetch(`/api/crawl/sources/${sourceId}/retry`, { method: 'POST' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export default function CrawlPage() {
  const {
    jobs,
    loading,
    error,
    fetchJobs,
    retryJob,
  } = useCrawlStore();

  const [sources, setSources] = useState<CrawlSource[]>([]);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<SourceTab>('manual');
  const [competitor, setCompetitor] = useState('');
  const [dimension, setDimension] = useState('');
  const [priority, setPriority] = useState(100);

  const fetchSources = async () => {
    setSourceError(null);
    try {
      const listed = await listSources();
      const withProgress = await Promise.all(listed.map(async (source) => {
        try {
          const detail = await getSourceDetail(source.id);
          return {
            ...detail.source,
            config: {
              ...detail.source.config,
              progress: detail.progress,
            },
          };
        } catch {
          return source;
        }
      }));
      setSources(withProgress);
    } catch (err) {
      setSourceError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void fetchJobs();
    void fetchSources();
  }, [fetchJobs]);

  useEffect(() => () => {
    useCrawlStore.getState().stopPolling();
  }, []);

  const refreshAll = async () => {
    await Promise.all([fetchJobs(), fetchSources()]);
  };

  const retryCrawlJob = async (jobId: string) => {
    await retryJob(jobId);
    await fetchJobs();
  };

  const retryCrawlSource = async (sourceId: string) => {
    try {
      await retrySource(sourceId);
      await refreshAll();
    } catch (err) {
      setSourceError(err instanceof Error ? err.message : String(err));
    }
  };

  const activeJobs = useMemo(() => (
    jobs.filter((job) => ['pending', 'running'].includes(job.status)).length
  ), [jobs]);

  const sourceProps = {
    competitor: competitor.trim() || undefined,
    dimension: dimension.trim() || undefined,
    priority,
    onSubmitted: refreshAll,
  };

  return (
    <div className="max-w-6xl mx-auto p-4 sm:p-6 space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-base-300 pb-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-primary to-secondary bg-clip-text text-transparent flex items-center gap-2">
            <Sparkles className="w-8 h-8 text-primary" />
            Crawl Jobs
          </h1>
          <p className="text-sm text-base-content/60 mt-1">
            Create multi-source crawl inputs, review queue progress, and retry failed URLs.
          </p>
        </div>
        <button type="button" className="btn btn-outline btn-sm gap-1" onClick={refreshAll} disabled={loading}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      <section className="rounded-lg border border-base-300 bg-base-200 p-4 sm:p-5 space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <input
            className="input input-bordered"
            placeholder="Competitor (optional)"
            value={competitor}
            onChange={(event) => setCompetitor(event.target.value)}
          />
          <input
            className="input input-bordered"
            placeholder="Dimension (optional)"
            value={dimension}
            onChange={(event) => setDimension(event.target.value)}
          />
          <input
            className="input input-bordered"
            type="number"
            min={1}
            value={priority}
            onChange={(event) => setPriority(Number(event.target.value))}
            aria-label="Queue priority"
          />
        </div>

        <div className="tabs tabs-boxed bg-base-100 p-1">
          {(['manual', 'sitemap', 'rss'] as const).map((tab) => (
            <button
              type="button"
              key={tab}
              className={`tab capitalize ${activeTab === tab ? 'tab-active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {tab === 'manual' ? 'URL list' : tab}
            </button>
          ))}
        </div>

        {activeTab === 'manual' && <ManualTab {...sourceProps} />}
        {activeTab === 'sitemap' && <SitemapTab {...sourceProps} />}
        {activeTab === 'rss' && <RssTab {...sourceProps} />}
      </section>

      {(error || sourceError) && (
        <div className="alert alert-error shadow-sm border border-error/20 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          <div className="text-sm">
            <h3 className="font-bold">Execution Error</h3>
            <p className="opacity-90">{error || sourceError}</p>
          </div>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-4">
        <div className="rounded-lg bg-base-200 p-3">
          <span className="text-xs text-base-content/55">Jobs</span>
          <strong className="block text-lg">{jobs.length}</strong>
        </div>
        <div className="rounded-lg bg-base-200 p-3">
          <span className="text-xs text-base-content/55">Active</span>
          <strong className="block text-lg">{activeJobs}</strong>
        </div>
        <div className="rounded-lg bg-base-200 p-3">
          <span className="text-xs text-base-content/55">Sources</span>
          <strong className="block text-lg">{sources.length}</strong>
        </div>
        <div className="rounded-lg bg-base-200 p-3">
          <span className="text-xs text-base-content/55">Failed</span>
          <strong className="block text-lg">{jobs.filter((job) => job.status === 'failed').length}</strong>
        </div>
      </div>

      <JobQueueTable
        jobs={jobs}
        sources={sources}
        onRetryJob={retryCrawlJob}
        onRetrySource={retryCrawlSource}
      />

      <FailedUrlsPanel
        jobs={jobs}
        sources={sources}
        onRetryJob={retryCrawlJob}
        onRetrySource={retryCrawlSource}
      />
    </div>
  );
}
