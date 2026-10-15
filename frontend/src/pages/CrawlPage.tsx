import { apiFetch } from "../api/http";
import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, RefreshCw, Sparkles } from 'lucide-react';
import { useCrawlStore } from '../stores/crawlStore';
import { ManualTab } from '../features/crawl/ManualTab';
import { SitemapTab } from '../features/crawl/SitemapTab';
import { RssTab } from '../features/crawl/RssTab';
import { JobQueueTable, type CrawlSource } from '../features/crawl/JobQueueTable';
import { FailedUrlsPanel } from '../features/crawl/FailedUrlsPanel';
import { useTranslation } from '../stores/i18n';
import { SystemMessage } from '../i18n/SystemMessage';

import { KnowledgeScopeControl, knowledgeScopeUrl, useKnowledgeWorkScope, type KnowledgeWorkScope } from '../features/knowledge/KnowledgeScopeControl';

type SourceTab = 'manual' | 'sitemap' | 'rss';

interface CrawlSourceDetail {
  source: CrawlSource;
  progress: Record<string, number>;
}

async function listSources(scope: KnowledgeWorkScope): Promise<CrawlSource[]> {
  const res = await apiFetch(knowledgeScopeUrl('/api/crawl/sources', scope));
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<CrawlSource[]>;
}

async function getSourceDetail(sourceId: string, scope: KnowledgeWorkScope): Promise<CrawlSourceDetail> {
  const res = await apiFetch(knowledgeScopeUrl(`/api/crawl/sources/${encodeURIComponent(sourceId)}`, scope));
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<CrawlSourceDetail>;
}

async function retrySource(sourceId: string, scope: KnowledgeWorkScope): Promise<void> {
  const res = await apiFetch(knowledgeScopeUrl(`/api/crawl/sources/${encodeURIComponent(sourceId)}/retry`, scope, true), { method: 'POST' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export default function CrawlPage() {
  const workScope = useKnowledgeWorkScope();
  return <div><KnowledgeScopeControl value={workScope} />{workScope.ready ? <ScopedCrawlPage key={workScope.key} scope={workScope.scope} /> : null}</div>;
}

function ScopedCrawlPage({ scope }: { scope: KnowledgeWorkScope }) {
  const { t } = useTranslation();
  const {
    jobs,
    loading,
    error,
    fetchJobs,
    retryJob,
  } = useCrawlStore();

  const active = useRef(true);
  const sourceRequest = useRef(0);
  const [sources, setSources] = useState<CrawlSource[]>([]);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<SourceTab>('manual');
  const [competitor, setCompetitor] = useState('');
  const [dimension, setDimension] = useState('');
  const [priority, setPriority] = useState(100);

  const fetchSources = async () => {
    if (!active.current) return;
    const request = ++sourceRequest.current;
    setSourceError(null);
    try {
      const listed = await listSources(scope);
      const withProgress = await Promise.all(listed.map(async (source) => {
        try {
          const detail = await getSourceDetail(source.id, scope);
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
      if (active.current && request === sourceRequest.current) setSources(withProgress);
    } catch (err) {
      if (active.current && request === sourceRequest.current) setSourceError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    active.current = true;
    useCrawlStore.getState().setScope(scope);
    void fetchJobs();
    void fetchSources();
    return () => { active.current = false; sourceRequest.current += 1; useCrawlStore.getState().setScope(null); };
  }, [fetchJobs]);

  useEffect(() => () => {
    useCrawlStore.getState().stopPolling();
  }, []);

  const refreshAll = async () => {
    if (active.current) await Promise.all([fetchJobs(), fetchSources()]);
  };

  const retryCrawlJob = async (jobId: string) => {
    await retryJob(jobId);
    await fetchJobs();
  };

  const retryCrawlSource = async (sourceId: string) => {
    try {
      const source = sources.find(item => item.id === sourceId);
      if (!source || (source.project_id ?? null) !== scope.projectId) return;
      await retrySource(sourceId, scope);
      await refreshAll();
    } catch (err) {
      if (active.current) setSourceError(err instanceof Error ? err.message : String(err));
    }
  };

  const activeJobs = useMemo(() => (
    jobs.filter((job) => ['pending', 'running'].includes(job.status)).length
  ), [jobs]);

  const sourceProps = {
    projectId: scope.projectId,
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
            {t('crawl.title')}
          </h1>
          <p className="text-sm text-base-content/60 mt-1">
            {t('crawl.description')}
          </p>
        </div>
        <button type="button" className="btn btn-outline btn-sm gap-1" onClick={refreshAll} disabled={loading}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          {t('common.refresh')}
        </button>
      </div>

      <section className="rounded-lg border border-base-300 bg-base-200 p-4 sm:p-5 space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <input
            className="input input-bordered"
            placeholder={t('crawl.competitor')}
            value={competitor}
            onChange={(event) => setCompetitor(event.target.value)}
          />
          <input
            className="input input-bordered"
            placeholder={t('crawl.dimension')}
            value={dimension}
            onChange={(event) => setDimension(event.target.value)}
          />
          <input
            className="input input-bordered"
            type="number"
            min={1}
            value={priority}
            onChange={(event) => setPriority(Number(event.target.value))}
            aria-label={t('crawl.queuePriority')}
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
              {tab === 'manual' ? t('crawl.urlList') : t(`crawl.${tab}`)}
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
            <h3 className="font-bold">{t('crawl.executionError')}</h3>
            <p className="opacity-90"><SystemMessage message={error || sourceError || ''} /></p>
          </div>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-4">
        <div className="rounded-lg bg-base-200 p-3">
          <span className="text-xs text-base-content/55">{t('crawl.jobs')}</span>
          <strong className="block text-lg">{jobs.length}</strong>
        </div>
        <div className="rounded-lg bg-base-200 p-3">
          <span className="text-xs text-base-content/55">{t('crawl.active')}</span>
          <strong className="block text-lg">{activeJobs}</strong>
        </div>
        <div className="rounded-lg bg-base-200 p-3">
          <span className="text-xs text-base-content/55">{t('crawl.sources')}</span>
          <strong className="block text-lg">{sources.length}</strong>
        </div>
        <div className="rounded-lg bg-base-200 p-3">
          <span className="text-xs text-base-content/55">{t('crawl.failed')}</span>
          <strong className="block text-lg">{jobs.filter((job) => job.status === 'failed').length}</strong>
        </div>
      </div>

      <p className="muted-line">尚未提供单任务重试或删除，请从所属来源重新采集。</p>
      {sources.some(source => (source.project_id ?? null) !== scope.projectId) || jobs.some(job => (job.project_id ?? null) !== scope.projectId) ? <p className="muted-line">公共库条目只读</p> : null}
      <JobQueueTable
        jobs={jobs}
        sources={sources}
        onRetryJob={retryCrawlJob}
        onRetrySource={retryCrawlSource}
        canRetryJob={() => false}
        canRetrySource={source => (source.project_id ?? null) === scope.projectId}
      />

      <FailedUrlsPanel
        jobs={jobs}
        sources={sources}
        onRetryJob={retryCrawlJob}
        onRetrySource={retryCrawlSource}
        canRetryJob={() => false}
        canRetrySource={source => (source.project_id ?? null) === scope.projectId}
      />
    </div>
  );
}
