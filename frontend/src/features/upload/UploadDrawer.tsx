import { ChangeEvent, DragEvent, useMemo, useState } from 'react';
import { UploadCloud, RotateCw, X } from 'lucide-react';
import { useTranslation } from '../../stores/i18n';
import {
  createBatch,
  fileToBase64,
  getIngestJob,
  type BatchIngestItem,
  type IngestJob,
  type UploadItemStatus,
} from '../../api/batch';

const ACCEPTED_EXTENSIONS = ['.pdf', '.docx', '.csv', '.json', '.md', '.html', '.txt'];
const DEFAULT_MAX_MB = 50;

interface UploadEntry {
  id: string;
  file: File;
  status: UploadItemStatus;
  progress: number;
  error?: string;
  documentId?: string;
}

interface UploadDrawerProps {
  open: boolean;
  onClose: () => void;
  onComplete: () => void;
}

function maxUploadBytes() {
  const env = (import.meta as unknown as { env?: Record<string, string> }).env;
  const configured = Number(env?.VITE_MAX_UPLOAD_MB ?? DEFAULT_MAX_MB);
  const mb = Number.isFinite(configured) && configured > 0 ? configured : DEFAULT_MAX_MB;
  return mb * 1024 * 1024;
}

function isAccepted(file: File) {
  const lowerName = file.name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lowerName.endsWith(ext));
}

function statusClass(status: UploadItemStatus) {
  if (status === 'failed') return 'bg-error/10 text-error border-error/25';
  if (status === 'ingested') return 'bg-success/10 text-success border-success/25';
  if (status === 'uploading' || status === 'parsed' || status === 'embedded') {
    return 'bg-info/10 text-info border-info/25';
  }
  return 'bg-base-200 text-base-content/60 border-base-300';
}

function applyJobProgress(entries: UploadEntry[], job: IngestJob): UploadEntry[] {
  const failed = new Map<number, string>();
  for (const item of job.failed) {
    if (typeof item.index === 'number') {
      failed.set(item.index, String(item.reason ?? 'Ingest failed'));
    }
  }

  const results = new Map<number, string>();
  for (const item of job.results) {
    if (typeof item.index === 'number') {
      results.set(item.index, String(item.document_id ?? ''));
    }
  }

  return entries.map((entry, index) => {
    if (failed.has(index)) {
      return { ...entry, status: 'failed', progress: 100, error: failed.get(index) };
    }
    if (results.has(index)) {
      return { ...entry, status: 'ingested', progress: 100, documentId: results.get(index) };
    }
    if (entry.status === 'uploading') {
      return { ...entry, status: 'parsed', progress: 45 };
    }
    if (entry.status === 'parsed') {
      return { ...entry, status: 'embedded', progress: 70 };
    }
    return entry;
  });
}

export function UploadDrawer({ open, onClose, onComplete }: UploadDrawerProps) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<UploadEntry[]>([]);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const maxBytes = useMemo(() => maxUploadBytes(), []);
  const maxMb = Math.round(maxBytes / 1024 / 1024);
  const canSubmit = entries.some((entry) => entry.status === 'queued' || entry.status === 'failed');

  const addFiles = (files: FileList | File[]) => {
    const next: UploadEntry[] = [];
    for (const file of Array.from(files)) {
      const base = {
        id: `${file.name}-${file.lastModified}-${crypto.randomUUID()}`,
        file,
        progress: 0,
      };
      if (!isAccepted(file)) {
        next.push({ ...base, status: 'failed', error: 'Unsupported file type' });
      } else if (file.size > maxBytes) {
        next.push({ ...base, status: 'failed', error: `File exceeds ${maxMb}MB` });
      } else {
        next.push({ ...base, status: 'queued' });
      }
    }
    setEntries((current) => [...current, ...next]);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    addFiles(event.dataTransfer.files);
  };

  const handleFileInput = (event: ChangeEvent<HTMLInputElement>) => {
    if (event.target.files) {
      addFiles(event.target.files);
      event.target.value = '';
    }
  };

  const pollJob = async (jobId: string, indexes: Set<number>) => {
    let done = false;
    while (!done) {
      await new Promise((resolve) => setTimeout(resolve, 900));
      const job = await getIngestJob(jobId);
      setEntries((current) => applyJobProgress(current, job));
      done = ['success', 'failed'].includes(job.status)
        || job.completed_items >= indexes.size
        || job.completed_items + job.failed_items >= indexes.size;
    }
  };

  const submitEntries = async (retryOnly = false) => {
    const targets = entries
      .map((entry, index) => ({ entry, index }))
      .filter(({ entry }) => retryOnly ? entry.status === 'failed' && isAccepted(entry.file) && entry.file.size <= maxBytes : entry.status === 'queued');

    if (targets.length === 0) return;
    setSubmitting(true);
    const indexes = new Set(targets.map(({ index }) => index));
    setEntries((current) => current.map((entry, index) => (
      indexes.has(index) ? { ...entry, status: 'uploading', progress: 20, error: undefined } : entry
    )));

    try {
      const items: BatchIngestItem[] = await Promise.all(targets.map(async ({ entry }) => ({
        source: 'base64',
        title: entry.file.name,
        filename: entry.file.name,
        mime: entry.file.type || undefined,
        content_b64: await fileToBase64(entry.file),
      })));
      const response = await createBatch(items);
      const rejected = new Map(response.rejected.map((item) => [item.index, item.reason]));
      setEntries((current) => current.map((entry, index) => {
        if (!indexes.has(index)) return entry;
        const targetPosition = targets.findIndex((target) => target.index === index);
        if (rejected.has(targetPosition)) {
          return { ...entry, status: 'failed', progress: 100, error: rejected.get(targetPosition) };
        }
        return { ...entry, status: 'parsed', progress: 45 };
      }));
      await pollJob(response.job_id, indexes);
      onComplete();
    } catch (err) {
      setEntries((current) => current.map((entry, index) => (
        indexes.has(index)
          ? { ...entry, status: 'failed', progress: 100, error: err instanceof Error ? err.message : String(err) }
          : entry
      )));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={`fixed inset-0 z-50 ${open ? '' : 'pointer-events-none'}`} aria-hidden={!open}>
      <div
        className={`absolute inset-0 bg-black/30 transition-opacity ${open ? 'opacity-100' : 'opacity-0'}`}
        onClick={onClose}
      />
      <aside className={`absolute right-0 top-0 h-full w-full max-w-2xl bg-base-100 shadow-2xl transition-transform ${open ? 'translate-x-0' : 'translate-x-full'}`}>
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b border-base-300 p-5">
            <div>
              <h2 className="text-lg font-bold">{t('upload.title')}</h2>
              <p className="text-xs text-base-content/60">PDF, DOCX, CSV, JSON, Markdown, HTML, and text up to {maxMb}MB each.</p>
            </div>
            <button type="button" className="btn btn-ghost btn-sm btn-circle" onClick={onClose} aria-label="Close upload drawer">
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto p-5">
            <div
              className={`grid min-h-40 place-items-center rounded-lg border-2 border-dashed p-6 text-center transition-colors ${dragging ? 'border-primary bg-primary/5' : 'border-base-300 bg-base-200/60'}`}
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={handleDrop}
            >
              <label className="flex cursor-pointer flex-col items-center gap-3">
                <UploadCloud className="h-9 w-9 text-primary" />
                <span className="text-sm font-semibold">{t('upload.dropFiles')}</span>
                <span className="text-xs text-base-content/55">{ACCEPTED_EXTENSIONS.join(' ')}</span>
                <input className="hidden" type="file" multiple accept={ACCEPTED_EXTENSIONS.join(',')} onChange={handleFileInput} />
              </label>
            </div>

            <div className="space-y-2">
              {entries.map((entry) => (
                <div key={entry.id} className="rounded-lg border border-base-300 bg-base-100 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold">{entry.file.name}</p>
                      <p className="text-xs text-base-content/55">{(entry.file.size / 1024 / 1024).toFixed(2)}MB</p>
                    </div>
                    <span className={`rounded-full border px-2 py-1 text-[11px] font-semibold ${statusClass(entry.status)}`}>
                      {entry.status}
                    </span>
                  </div>
                  <progress className="progress progress-primary mt-3 h-2 w-full" value={entry.progress} max={100} />
                  {entry.error && <p className="mt-2 text-xs text-error">{entry.error}</p>}
                </div>
              ))}
              {entries.length === 0 && (
                <p className="rounded-lg border border-dashed border-base-300 p-6 text-center text-sm text-base-content/50">
                  {t('upload.noFiles')}
                </p>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-base-300 p-5">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEntries([])} disabled={submitting || entries.length === 0}>
              Clear
            </button>
            <div className="flex gap-2">
              <button type="button" className="btn btn-outline btn-sm gap-1" onClick={() => submitEntries(true)} disabled={submitting || !entries.some((entry) => entry.status === 'failed')}>
                <RotateCw className="h-3.5 w-3.5" />
                {t('upload.retryFailed')}
              </button>
              <button type="button" className="btn btn-primary btn-sm" onClick={() => submitEntries(false)} disabled={submitting || !canSubmit}>
                {submitting ? 'Uploading...' : t('upload.startUpload')}
              </button>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
