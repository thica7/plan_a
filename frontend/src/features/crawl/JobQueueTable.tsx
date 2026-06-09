import { useMemo, useState } from 'react';
import { GripVertical, Pause, Play, RotateCw } from 'lucide-react';
import type { CrawlJob } from '../../api/crawl';

export interface CrawlSource {
  id: string;
  type: 'sitemap' | 'rss' | 'web_search' | 'manual' | string;
  config: Record<string, unknown>;
  created_at: string;
}

interface JobQueueTableProps {
  jobs: CrawlJob[];
  sources: CrawlSource[];
  onRetryJob: (jobId: string) => Promise<void>;
  onRetrySource: (sourceId: string) => Promise<void>;
}

interface QueueRow {
  id: string;
  label: string;
  sourceType: string;
  status: string;
  priority: number;
  progress: number;
  kind: 'job' | 'source';
  createdAt: string;
}

function sourceLabel(source: CrawlSource) {
  const config = source.config;
  if (typeof config.url === 'string') return config.url;
  if (Array.isArray(config.urls)) return `${config.urls.length} manual URLs`;
  return source.id;
}

function sourceProgress(source: CrawlSource) {
  const stats = source.config.progress as Record<string, number> | undefined;
  if (!stats) return 0;
  const total = Object.values(stats).reduce((sum, value) => sum + Number(value || 0), 0);
  if (total === 0) return 0;
  return Math.round(((Number(stats.done || 0) + Number(stats.failed || 0)) / total) * 100);
}

export function JobQueueTable({ jobs, sources, onRetryJob, onRetrySource }: JobQueueTableProps) {
  const [order, setOrder] = useState<string[]>([]);
  const [paused, setPaused] = useState<Set<string>>(() => new Set());

  const rows = useMemo<QueueRow[]>(() => {
    const jobRows = jobs.map((job) => ({
      id: `job:${job.id}`,
      label: job.url,
      sourceType: job.run_id ? 'source job' : 'manual job',
      status: job.status,
      priority: 100,
      progress: job.status === 'completed' || job.status === 'success' ? 100 : job.status === 'running' ? 60 : job.status === 'failed' ? 100 : 10,
      kind: 'job' as const,
      createdAt: job.created_at,
    }));
    const sourceRows = sources.map((source) => ({
      id: `source:${source.id}`,
      label: sourceLabel(source),
      sourceType: source.type,
      status: 'source',
      priority: Number(source.config.priority ?? 100),
      progress: sourceProgress(source),
      kind: 'source' as const,
      createdAt: source.created_at,
    }));
    const combined = [...sourceRows, ...jobRows];
    return combined.sort((a, b) => {
      const aIndex = order.indexOf(a.id);
      const bIndex = order.indexOf(b.id);
      if (aIndex >= 0 || bIndex >= 0) return (aIndex < 0 ? 9999 : aIndex) - (bIndex < 0 ? 9999 : bIndex);
      return a.priority - b.priority || new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
    });
  }, [jobs, sources, order]);

  const move = (id: string, delta: number) => {
    const current = order.length > 0 ? order : rows.map((row) => row.id);
    const index = current.indexOf(id);
    const nextIndex = index + delta;
    if (index < 0 || nextIndex < 0 || nextIndex >= current.length) return;
    const next = [...current];
    [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
    setOrder(next);
  };

  const togglePaused = (id: string) => {
    setPaused((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="overflow-x-auto rounded-lg border border-base-300 bg-base-100">
      <table className="table w-full">
        <thead>
          <tr>
            <th>Queue</th>
            <th>Target</th>
            <th>Status</th>
            <th>Priority</th>
            <th>Progress</th>
            <th>Source</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const isPaused = paused.has(row.id);
            const rawId = row.id.split(':')[1];
            return (
              <tr key={row.id} className={isPaused ? 'opacity-55' : ''}>
                <td>
                  <div className="flex items-center gap-1">
                    <GripVertical className="h-4 w-4 text-base-content/40" />
                    <button type="button" className="btn btn-ghost btn-xs" onClick={() => move(row.id, -1)} disabled={index === 0}>Up</button>
                    <button type="button" className="btn btn-ghost btn-xs" onClick={() => move(row.id, 1)} disabled={index === rows.length - 1}>Down</button>
                  </div>
                </td>
                <td className="max-w-md truncate text-sm">{row.label}</td>
                <td>
                  <span className="badge badge-sm">{isPaused ? 'paused' : row.status}</span>
                </td>
                <td>{row.priority}</td>
                <td>
                  <div className="flex items-center gap-2">
                    <progress className="progress progress-primary w-24" value={row.progress} max={100} />
                    <span className="text-xs">{row.progress}%</span>
                  </div>
                </td>
                <td>{row.sourceType}</td>
                <td>
                  <div className="flex flex-wrap gap-1">
                    <button type="button" className="btn btn-ghost btn-xs gap-1" onClick={() => togglePaused(row.id)}>
                      {isPaused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
                      {isPaused ? 'Resume' : 'Pause'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-outline btn-xs gap-1"
                      onClick={() => row.kind === 'source' ? onRetrySource(rawId) : onRetryJob(rawId)}
                      disabled={row.kind === 'job' && !['failed', 'completed', 'success'].includes(row.status)}
                    >
                      <RotateCw className="h-3 w-3" />
                      Retry
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr>
              <td colSpan={7} className="py-8 text-center text-sm text-base-content/50">No queued jobs or sources.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
