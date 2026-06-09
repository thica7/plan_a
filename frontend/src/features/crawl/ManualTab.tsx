import { useMemo, useState } from 'react';

interface ManualTabProps {
  competitor?: string;
  dimension?: string;
  priority: number;
  onSubmitted: () => void;
}

async function createManualSource(urls: string[], config: Record<string, unknown>) {
  const res = await fetch('/api/crawl/sources', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      type: 'manual',
      config: { urls, max_urls: urls.length, ...config },
    }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export function ManualTab({ competitor, dimension, priority, onSubmitted }: ManualTabProps) {
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
      await createManualSource(urls, { competitor, dimension, priority });
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
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
      {error && <div className="alert alert-error text-sm">{error}</div>}
      <div className="rounded-lg border border-base-300 bg-base-100 p-3">
        <div className="mb-2 flex items-center justify-between text-xs">
          <span className="font-semibold">Preview</span>
          <span className="text-base-content/55">{urls.length} URLs</span>
        </div>
        <ol className="grid gap-1 text-xs">
          {urls.slice(0, 10).map((url) => <li key={url} className="truncate">{url}</li>)}
          {urls.length === 0 && <li className="text-base-content/50">No URLs discovered.</li>}
        </ol>
      </div>
      <button type="button" className="btn btn-primary btn-sm w-fit" onClick={submit} disabled={submitting || urls.length === 0}>
        {submitting ? 'Submitting...' : 'Submit URL list'}
      </button>
    </div>
  );
}
