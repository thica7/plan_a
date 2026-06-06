import { useState, MouseEvent } from 'react';

/** Reusable source card for displaying a knowledge document or retrieval hit. */

interface SourceCardProps {
  title: string;
  url: string | null;
  competitor: string | null;
  dimension: string | null;
  source_type: string;
  snippet?: string;
  fetched_at?: string;
  score?: number;
  rerank_score?: number | null;
  onClick?: () => void;
}

export function SourceCard({
  title,
  url,
  competitor,
  dimension,
  source_type,
  snippet,
  fetched_at,
  score,
  rerank_score,
  onClick,
}: SourceCardProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e: MouseEvent) => {
    e.stopPropagation();
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy URL:', err);
    }
  };

  return (
    <div
      className="card bg-base-100 border border-base-300 p-4 space-y-2 hover:shadow-lg hover:-translate-y-0.5 transition-all duration-200 cursor-pointer"
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <h3 className="font-semibold text-sm leading-tight">
            {url ? (
              <a href={url} target="_blank" rel="noopener noreferrer" className="link link-primary">
                {title}
              </a>
            ) : (
              title
            )}
          </h3>
          {url && (
            <button
              onClick={handleCopy}
              className="btn btn-ghost btn-xs btn-circle text-base-content/50 hover:text-base-content flex-shrink-0"
              title="Copy URL"
              type="button"
            >
              {copied ? (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={2.5}
                  stroke="currentColor"
                  className="w-3.5 h-3.5 text-success"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
              ) : (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={2}
                  stroke="currentColor"
                  className="w-3.5 h-3.5"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M16.5 8.25V6a2.25 2.25 0 00-2.25-2.25H6A2.25 2.25 0 003.75 6v8.25A2.25 2.25 0 006 16.5h2.25m8.25-8.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-7.5A2.25 2.25 0 018.25 18v-1.5m8.25-8.25h-6a2.25 2.25 0 00-2.25 2.25v6"
                  />
                </svg>
              )}
            </button>
          )}
        </div>
        {score != null && (
          <div className="flex items-center gap-1.5 flex-shrink-0">
            <progress
              className={`progress w-12 ${
                score > 0.7
                  ? 'progress-success'
                  : score > 0.4
                  ? 'progress-warning'
                  : 'progress-error'
              }`}
              value={score}
              max={1}
            />
            <span className="text-xs font-semibold">{(score * 100).toFixed(0)}%</span>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5 text-xs">
        {competitor && <span className="badge badge-sm">{competitor}</span>}
        {dimension && <span className="badge badge-sm badge-accent">{dimension}</span>}
        <span className="badge badge-sm badge-ghost">{source_type}</span>
        {rerank_score != null && (
          <span className="badge badge-sm badge-primary">rerank: {(rerank_score * 100).toFixed(0)}</span>
        )}
      </div>

      {snippet && <p className="text-xs text-base-content/70 line-clamp-3">{snippet}</p>}

      {fetched_at && (
        <time className="text-xs text-base-content/40">
          {new Date(fetched_at).toLocaleDateString()}
        </time>
      )}
    </div>
  );
}

