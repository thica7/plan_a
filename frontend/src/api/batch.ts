export type UploadItemStatus = 'queued' | 'uploading' | 'parsed' | 'embedded' | 'ingested' | 'failed';

export interface BatchIngestItem {
  source: 'base64';
  title?: string | null;
  content_b64: string;
  mime?: string | null;
  filename?: string | null;
}

export interface BatchIngestResponse {
  job_id: string;
  accepted: number;
  rejected: Array<{ index: number; reason: string }>;
}

export interface IngestJob {
  id: string;
  status: string;
  total_items: number;
  accepted_items: number;
  completed_items: number;
  failed_items: number;
  rejected: Array<Record<string, unknown>>;
  failed: Array<Record<string, unknown>>;
  results: Array<Record<string, unknown>>;
  options: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export async function createBatch(items: BatchIngestItem[], maxConcurrent = 4): Promise<BatchIngestResponse> {
  const res = await fetch('/api/knowledge/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      items,
      options: {
        max_concurrent: maxConcurrent,
        fail_fast: false,
      },
    }),
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json() as Promise<BatchIngestResponse>;
}

export async function getIngestJob(jobId: string, signal?: AbortSignal): Promise<IngestJob> {
  const res = await fetch(`/api/knowledge/ingest-jobs/${jobId}`, { signal });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json() as Promise<IngestJob>;
}

export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error('Unable to read file'));
    reader.onload = () => {
      const value = String(reader.result ?? '');
      const comma = value.indexOf(',');
      resolve(comma >= 0 ? value.slice(comma + 1) : value);
    };
    reader.readAsDataURL(file);
  });
}
