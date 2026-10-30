import { apiFetch } from './http';
import type { QuotaLedgerPage, RuntimeConfig, SubmissionCreateRequest, SubmissionPage, SubmissionView } from './types';

/** Keep machine-readable failures without exposing server HTML or exception text. */
export class SubmissionApiError extends Error {
  constructor(public readonly status: number, public readonly code: string) {
    super('Submission request failed');
    this.name = 'SubmissionApiError';
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  try {
    const response = await apiFetch(path, init);
    if (!response.ok) {
      const body: unknown = await response.json().catch(() => null);
      const code = body && typeof body === 'object' && 'code' in body && typeof body.code === 'string'
        ? body.code : 'http_error';
      throw new SubmissionApiError(response.status, code);
    }
    return await response.json() as T;
  } catch (error) {
    if (error instanceof SubmissionApiError || (typeof error === 'object' && error !== null && 'name' in error && error.name === 'AbortError')) throw error;
    throw new SubmissionApiError(0, 'connection_error');
  }
}

export function submissionErrorKey(error: unknown): string {
  if (!(error instanceof SubmissionApiError)) return 'submissions.error.connection';
  if (error.code === 'task_center_disabled') return 'submissions.error.disabled';
  if (error.code === 'quota_exceeded') return 'submissions.error.quota';
  if (error.code === 'idempotency_conflict') return 'submissions.error.intent';
  if (error.status === 401 || error.status === 403) return 'submissions.error.permission';
  if (error.status === 404) return 'submissions.error.notFound';
  if (error.status === 409) return 'submissions.error.conflict';
  if (error.status === 429) return 'submissions.error.quota';
  if (error.status === 400 || error.status === 422) return 'submissions.error.invalid';
  if (error.status >= 500) return 'submissions.error.unavailable';
  return 'submissions.error.connection';
}

export function createSubmission(body: SubmissionCreateRequest, signal?: AbortSignal) {
  return request<SubmissionView>('/api/task-submissions', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  });
}


function query(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => { if (value !== undefined && value !== '') params.set(key, String(value)); });
  return params.size ? `?${params}` : '';
}

export function getSubmissionRuntime(signal?: AbortSignal) {
  return request<RuntimeConfig>('/api/runtime', { signal });
}
export function listSubmissions(options: { workspaceId: string; status?: SubmissionView['status']; cursor?: string; limit?: number }, signal?: AbortSignal) {
  return request<SubmissionPage>(`/api/task-submissions${query({ workspace_id: options.workspaceId, status: options.status, cursor: options.cursor, limit: options.limit ?? 20 })}`, { signal });
}
export function getSubmission(id: string, workspaceId: string, signal?: AbortSignal) {
  return request<SubmissionView>(`/api/task-submissions/${encodeURIComponent(id)}${query({ workspace_id: workspaceId })}`, { signal });
}
export function cancelSubmission(id: string, workspaceId: string, signal?: AbortSignal) {
  return request<SubmissionView>(`/api/task-submissions/${encodeURIComponent(id)}/cancel${query({ workspace_id: workspaceId })}`, { method: 'POST', signal });
}
export function retrySubmissionDispatch(id: string, workspaceId: string, signal?: AbortSignal) {
  return request<SubmissionView>(`/api/task-submissions/${encodeURIComponent(id)}/retry-dispatch${query({ workspace_id: workspaceId })}`, { method: 'POST', signal });
}
export function getQuotaLedger(options: { workspaceId: string; periodStart?: string; cursor?: string; limit?: number }, signal?: AbortSignal) {
  return request<QuotaLedgerPage>(`/api/workspaces/${encodeURIComponent(options.workspaceId)}/quota-ledger${query({ period_start: options.periodStart, cursor: options.cursor, limit: options.limit ?? 20 })}`, { signal });
}
