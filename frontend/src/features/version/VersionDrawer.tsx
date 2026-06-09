import { useEffect, useMemo, useState } from 'react';
import { GitMerge, RefreshCw } from 'lucide-react';
import { useTranslation } from '../../stores/i18n';


interface VersionDocument {
  id: string;
  title: string;
  text: string;
  markdown?: string;
  content_hash: string;
  fetched_at: string;
  indexed_at?: string | null;
  version?: number;
  is_active?: boolean;
}

interface DocumentDiffResponse {
  document_id: string;
  against: string;
  diff: string[];
}

interface VersionDrawerProps {
  documentId: string;
  onMerged: () => void;
}

async function getVersions(documentId: string): Promise<VersionDocument[]> {
  const res = await fetch(`/api/knowledge/documents/${documentId}/versions`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<VersionDocument[]>;
}

async function getDiff(documentId: string, against: string): Promise<DocumentDiffResponse> {
  const params = new URLSearchParams({ against });
  const res = await fetch(`/api/knowledge/documents/${documentId}/diff?${params}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<DocumentDiffResponse>;
}

async function mergeVersion(documentId: string, targetDocumentId: string): Promise<VersionDocument> {
  const res = await fetch(`/api/knowledge/documents/${documentId}/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target_document_id: targetDocumentId }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<VersionDocument>;
}

function splitDiff(lines: string[]) {
  const left: string[] = [];
  const right: string[] = [];
  for (const line of lines) {
    if (line.startsWith('---') || line.startsWith('+++') || line.startsWith('@@')) continue;
    if (line.startsWith('-')) {
      left.push(line.slice(1));
      right.push('');
    } else if (line.startsWith('+')) {
      left.push('');
      right.push(line.slice(1));
    } else {
      const text = line.startsWith(' ') ? line.slice(1) : line;
      left.push(text);
      right.push(text);
    }
  }
  return { left, right };
}

export function VersionDrawer({ documentId, onMerged }: VersionDrawerProps) {
  const { t } = useTranslation();
  const [versions, setVersions] = useState<VersionDocument[]>([]);
  const [baseId, setBaseId] = useState('');
  const [targetId, setTargetId] = useState('');
  const [diff, setDiff] = useState<DocumentDiffResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [merging, setMerging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedDiff = useMemo(() => splitDiff(diff?.diff ?? []), [diff]);

  const loadVersions = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getVersions(documentId);
      setVersions(data);
      const active = data.find((version) => version.id === documentId) ?? data[data.length - 1];
      const previous = data.find((version) => version.id !== active?.id) ?? data[0];
      setTargetId(active?.id ?? '');
      setBaseId(previous?.id ?? active?.id ?? '');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadVersions();
  }, [documentId]);

  useEffect(() => {
    if (!baseId || !targetId || baseId === targetId) {
      setDiff(null);
      return;
    }
    let cancelled = false;
    void getDiff(targetId, baseId)
      .then((data) => {
        if (!cancelled) setDiff(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [baseId, targetId]);

  const handleMerge = async () => {
    if (!targetId) return;
    setMerging(true);
    setError(null);
    try {
      await mergeVersion(documentId, targetId);
      await loadVersions();
      onMerged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setMerging(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="font-bold">{t('version.title')}</h4>
          <p className="text-xs text-base-content/60">{versions.length} stored versions for this document lineage.</p>
        </div>
        <button type="button" className="btn btn-ghost btn-sm gap-1" onClick={loadVersions} disabled={loading}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          {t('version.refresh')}
        </button>
      </div>

      {error && <div className="alert alert-error text-sm">{error}</div>}

      <div className="grid gap-2">
        {versions.map((version) => (
          <button
            type="button"
            key={version.id}
            className={`rounded-lg border p-3 text-left transition-colors ${targetId === version.id ? 'border-primary bg-primary/5' : 'border-base-300 bg-base-100 hover:bg-base-200'}`}
            onClick={() => setTargetId(version.id)}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-semibold">Version {version.version ?? '-'}</span>
              <span className={version.is_active ? 'badge badge-success badge-sm' : 'badge badge-ghost badge-sm'}>
                {version.is_active ? 'active' : 'inactive'}
              </span>
            </div>
            <time className="mt-1 block text-xs text-base-content/55">{new Date(version.fetched_at).toLocaleString()}</time>
            <code className="mt-2 block truncate text-[11px] text-base-content/55">{version.content_hash}</code>
          </button>
        ))}
      </div>

      {versions.length > 1 && (
        <div className="grid gap-3 rounded-lg border border-base-300 bg-base-200/60 p-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-xs font-semibold">
              Compare from
              <select className="select select-bordered select-sm mt-1 w-full" value={baseId} onChange={(event) => setBaseId(event.target.value)}>
                {versions.map((version) => (
                  <option key={version.id} value={version.id}>v{version.version ?? '-'} {version.id.slice(0, 8)}</option>
                ))}
              </select>
            </label>
            <label className="text-xs font-semibold">
              Compare to
              <select className="select select-bordered select-sm mt-1 w-full" value={targetId} onChange={(event) => setTargetId(event.target.value)}>
                {versions.map((version) => (
                  <option key={version.id} value={version.id}>v{version.version ?? '-'} {version.id.slice(0, 8)}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <pre className="max-h-72 overflow-auto rounded-md bg-base-100 p-3 text-xs leading-relaxed">
              {selectedDiff.left.join('\n') || t('version.noDiff')}
            </pre>
            <pre className="max-h-72 overflow-auto rounded-md bg-base-100 p-3 text-xs leading-relaxed">
              {selectedDiff.right.join('\n') || t('version.noDiff')}
            </pre>
          </div>

          <button type="button" className="btn btn-primary btn-sm w-fit gap-1" onClick={handleMerge} disabled={merging || !targetId}>
            <GitMerge className="h-3.5 w-3.5" />
            {merging ? 'Merging...' : t('version.mergeSelected')}
          </button>
        </div>
      )}
    </div>
  );
}
