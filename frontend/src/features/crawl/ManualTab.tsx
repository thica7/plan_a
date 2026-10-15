import { apiFetch } from "../../api/http";
import { useMemo, useState } from 'react';
import { useTranslation } from '../../stores/i18n';
import { SystemMessage } from '../../i18n/SystemMessage';

interface ManualTabProps {
  projectId?: string | null;
  competitor?: string;
  dimension?: string;
  priority: number;
  onSubmitted: () => void;
}

async function createManualSource(urls: string[], config: Record<string, unknown>, projectId: string | null) {
  const res = await apiFetch(`/api/crawl/sources?${new URLSearchParams({ ...(projectId ? { project_id: projectId } : {}), include_workspace_library: 'false' })}`,  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project_id: projectId,
      type: 'manual',
      config: { urls, max_urls: urls.length, ...config },
    }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export function ManualTab({ projectId = null, competitor, dimension, priority, onSubmitted }: ManualTabProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const urls = useMemo(() => (
    value.split(/\r?\n/).map((url) => url.trim()).filter(Boolean)
  ), [value]);

  const submit = async () => {
    if (urls.length === 0) return;
    setSubmitting(true);
    setError(null);
    try {
      await createManualSource(urls, { competitor, dimension, priority }, projectId);
      setValue('');
      onSubmitted();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="grid gap-3">
      <textarea
        className="textarea textarea-bordered min-h-28 w-full font-mono text-sm"
        placeholder="https://example.com/pricing&#10;https://example.com/features"
        aria-label={t('crawl.urlList')}
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
      {error && <div className="alert alert-error text-sm"><SystemMessage message={error} /></div>}
      <div className="rounded-lg border border-base-300 bg-base-100 p-3">
        <div className="mb-2 flex items-center justify-between text-xs">
          <span className="font-semibold">{t('common.preview')}</span>
          <span className="text-base-content/55">{urls.length} {t('common.urls')}</span>
        </div>
        <ol className="grid gap-1 text-xs">
          {urls.slice(0, 10).map((url) => <li key={url} className="truncate">{url}</li>)}
          {urls.length === 0 && <li className="text-base-content/50">{t('crawl.noUrls')}</li>}
        </ol>
      </div>
      <button type="button" className="btn btn-primary btn-sm w-fit" onClick={submit} disabled={submitting || urls.length === 0}>
        {submitting ? t('crawl.submitting') : t('crawl.submitUrlList')}
      </button>
    </div>
  );
}
