import { RotateCw } from 'lucide-react';
import type { CrawlJob } from '../../api/crawl';
import type { CrawlSource } from './JobQueueTable';

interface FailedUrlsPanelProps {
  jobs: CrawlJob[];
  sources: CrawlSource[];
  onRetryJob: (jobId: string) => Promise<void>;
  onRetrySource: (sourceId: string) => Promise<void>;
}

export function FailedUrlsPanel({ jobs, sources, onRetryJob, onRetrySource }: FailedUrlsPanelProps) {
  const failedJobs = jobs.filter((job) => job.status === 'failed' && job.error);
  const failedSources = sources.filter((source) => {
    const progress = source.config.progress as Record<string, number> | undefined;
    return Number(progress?.failed ?? 0) > 0;
  });

  return (
    <section className="rounded-lg border border-base-300 bg-base-100 p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <h2 className="font-bold">Failed URLs</h2>
          <p className="text-xs text-base-content/60">Retry failed crawl jobs and source-driven failures.</p>
        </div>
        <span className="badge badge-error badge-sm">{failedJobs.length + failedSources.length}</span>
      </div>

      <div className="grid gap-2">
        {failedJobs.map((job) => (
          <div key={job.id} className="rounded-lg border border-error/20 bg-error/5 p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold">{job.url}</p>
                <p className="mt-1 text-xs text-error">{job.error}</p>
              </div>
              <button type="button" className="btn btn-outline btn-error btn-xs gap-1" onClick={() => onRetryJob(job.id)}>
                <RotateCw className="h-3 w-3" />
                Retry
              </button>
            </div>
          </div>
        ))}

        {failedSources.map((source) => {
          const progress = source.config.progress as Record<string, number> | undefined;
          const label = typeof source.config.url === 'string'
            ? source.config.url
            : Array.isArray(source.config.urls)
            ? `${source.config.urls.length} manual URLs`
            : source.id;
          return (
            <div key={source.id} className="rounded-lg border border-error/20 bg-error/5 p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{label}</p>
                  <p className="mt-1 text-xs text-error">{Number(progress?.failed ?? 0)} failed URLs in {source.type} source</p>
                </div>
                <button type="button" className="btn btn-outline btn-error btn-xs gap-1" onClick={() => onRetrySource(source.id)}>
                  <RotateCw className="h-3 w-3" />
                  Retry
                </button>
              </div>
            </div>
          );
        })}

        {failedJobs.length === 0 && failedSources.length === 0 && (
          <p className="rounded-lg border border-dashed border-base-300 p-4 text-center text-sm text-base-content/50">
            No failed URLs.
          </p>
        )}
      </div>
    </section>
  );
}
