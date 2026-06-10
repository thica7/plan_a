import { useState } from 'react';
import { Search } from 'lucide-react';
import { useTranslation } from '../../stores/i18n';

interface RssTabProps {
  competitor?: string;
  dimension?: string;
  priority: number;
  onSubmitted: () => void;
}

function parseFeedUrls(xml: string) {
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const entryLinks = Array.from(doc.querySelectorAll('entry link[href]'))
    .map((node) => node.getAttribute('href')?.trim() ?? '')
    .filter(Boolean);
  const itemLinks = Array.from(doc.querySelectorAll('item > link'))
    .map((node) => node.textContent?.trim() ?? '')
    .filter(Boolean);
  return [...entryLinks, ...itemLinks];
}

async function createRssSource(url: string, config: Record<string, unknown>) {
  const res = await fetch('/api/crawl/sources', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      type: 'rss',
      config: { url, ...config },
    }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export function RssTab({ competitor, dimension, priority, onSubmitted }: RssTabProps) {
  const { t } = useTranslation();
  const [url, setUrl] = useState('');
  const [maxUrls, setMaxUrls] = useState(100);
  const [preview, setPreview] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPreview = async () => {
    if (!url.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(url.trim());
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setPreview(parseFeedUrls(await res.text()).slice(0, 10));
    } catch (err) {
      setPreview([]);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const submit = async () => {
    if (!url.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await createRssSource(url.trim(), { competitor, dimension, priority, max_urls: maxUrls });
      setUrl('');
      setPreview([]);
      onSubmitted();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="grid gap-3">
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          className="input input-bordered flex-1"
          type="url"
          placeholder="https://example.com/feed.xml"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
        />
        <input
          className="input input-bordered w-28"
          type="number"
          min={1}
          max={1000}
          value={maxUrls}
          onChange={(event) => setMaxUrls(Number(event.target.value))}
          aria-label="Maximum URLs"
        />
        <button type="button" className="btn btn-outline btn-sm gap-1" onClick={loadPreview} disabled={loading || !url.trim()}>
          <Search className="h-3.5 w-3.5" />
          {t('common.preview')}
        </button>
      </div>
      {error && <div className="alert alert-error text-sm">{error}</div>}
      <div className="rounded-lg border border-base-300 bg-base-100 p-3">
        <div className="mb-2 flex items-center justify-between text-xs">
          <span className="font-semibold">{t('common.preview')}</span>
          <span className="text-base-content/55">{preview.length} shown</span>
        </div>
        <ol className="grid gap-1 text-xs">
          {preview.map((item) => <li key={item} className="truncate">{item}</li>)}
          {preview.length === 0 && <li className="text-base-content/50">{t('crawl.noUrlsYet')}</li>}
        </ol>
      </div>
      <button type="button" className="btn btn-primary btn-sm w-fit" onClick={submit} disabled={submitting || !url.trim()}>
        {submitting ? t('crawl.submitting') : t('crawl.submitRss')}
      </button>
    </div>
  );
}
