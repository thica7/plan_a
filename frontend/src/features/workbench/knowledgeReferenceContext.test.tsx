import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BusinessQAFinding } from '../../api/types';
import { createBatch, getIngestJob } from '../../api/batch';
import { useKnowledgeStore } from '../../stores/knowledgeStore';
import { buildReleaseIssueAuditRows, buildReleaseIssueRollbackTarget } from './releaseGateReview';

const initialState = useKnowledgeStore.getState();
function response(body: unknown, count = '0') {
  return { ok: true, status: 200, headers: new Headers({ 'X-Total-Count': count }), json: async () => body };
}
function finding(trail: Record<string, unknown>[], pairs: Record<string, unknown>[] = []) {
  return { id: 'issue', metadata: { evidence_audit_trail: trail, source_evidence_pairs: pairs } } as unknown as BusinessQAFinding;
}

afterEach(() => {
  const state = useKnowledgeStore.getState();
  if (state.errorTimer) clearTimeout(state.errorTimer);
  if (state.debounceTimer) clearTimeout(state.debounceTimer);
  useKnowledgeStore.setState(initialState, true);
  vi.unstubAllGlobals();
});

describe('knowledge reference context', () => {
  it('adds only typed KB project scope to each document, pair and raw-source link', () => {
    const item = { kb_document_id: 'doc', kb_raw_source_id: 'raw', kb_document_workspace_id: 'ws', kb_document_project_id: 'project-a', project_id: 'evil' };
    const rows = buildReleaseIssueAuditRows(finding([item], [{ ...item, kb_source_id: 'raw', live_source_id: 'live' }]));
    const links = rows.flatMap((row) => row.href ? [row.href] : []);
    expect(links).toHaveLength(3);
    for (const link of links) expect(new URL(link, 'https://example.test').searchParams.get('project_id')).toBe('project-a');
    const publicRows = buildReleaseIssueAuditRows(finding([{ ...item, kb_document_project_id: null }]));
    for (const row of publicRows) if (row.href) expect(row.href).not.toContain('project_id');
  });

  it('keeps explicit public rollback scope and refuses a mixed-scope bulk target', () => {
    const publicItem = { kb_document_id: 'public-doc', kb_document_workspace_id: 'ws', kb_document_project_id: null };
    expect(buildReleaseIssueRollbackTarget(finding([publicItem]))?.request).toEqual({ document_ids: ['public-doc'], restore_previous: true, project_id: null });
    expect(buildReleaseIssueRollbackTarget(finding([publicItem, { ...publicItem, kb_document_id: 'project-doc', kb_document_project_id: 'project-a' }]))).toBeNull();
    expect(buildReleaseIssueRollbackTarget(finding([{ ...publicItem, kb_document_project_id: 'project-a' }]))?.request.project_id).toBe('project-a');
  });

  it('keeps a workspace-known legacy reference unknown and refuses mixing it with explicit public', () => {
    const legacy = { kb_document_id: 'legacy', kb_document_workspace_id: 'ws' };
    const publicItem = { kb_document_id: 'public', kb_document_workspace_id: 'ws', kb_document_project_id: null };
    const target = buildReleaseIssueRollbackTarget(finding([legacy]));
    expect(target?.request).not.toHaveProperty('project_id');
    expect(buildReleaseIssueRollbackTarget(finding([legacy, publicItem]))).toBeNull();
  });

  it('requests project list pagination and discards a response after changing scope', async () => {
    let resolveOld!: (value: unknown) => void;
    const fetchMock = vi.fn().mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; })).mockResolvedValueOnce(response([{ id: 'public-doc' }], '1'));
    vi.stubGlobal('fetch', fetchMock);
    useKnowledgeStore.getState().setProjectId('project-a');
    const oldRequest = useKnowledgeStore.getState().fetchDocuments();
    useKnowledgeStore.getState().setProjectId(null);
    await useKnowledgeStore.getState().fetchDocuments();
    resolveOld(response([{ id: 'old-project-doc' }], '1'));
    await oldRequest;
    expect(fetchMock.mock.calls[0][0]).toBe('/api/knowledge/documents?project_id=project-a&limit=10&offset=0');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/knowledge/documents?limit=10&offset=0');
    expect(useKnowledgeStore.getState().documents.map((doc) => doc.id)).toEqual(['public-doc']);
  });

  it('uses explicit document write scope independently of the global page project', async () => {
    const result = { matched_count: 1, rolled_back_count: 1, restored_count: 0, archived_document_ids: ['doc'], restored_document_ids: [], skipped_document_ids: [] };
    const fetchMock = vi.fn((input: RequestInfo | URL) => Promise.resolve(response(String(input).includes('/rollback') ? result : [])));
    vi.stubGlobal('fetch', fetchMock);
    useKnowledgeStore.getState().setProjectId('unrelated-page-project');
    await useKnowledgeStore.getState().rollbackDocuments({ document_ids: ['doc'], project_id: null });
    expect(fetchMock.mock.calls[0][0]).toBe('/api/knowledge/documents/rollback');
    await useKnowledgeStore.getState().deleteDocument('doc', 'real-project');
    expect(fetchMock.mock.calls[fetchMock.mock.calls.length - 1][0]).toBe('/api/knowledge/documents/doc?project_id=real-project');
  });

  it('keeps batch creation and polling in the same project', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ job_id: 'job', accepted: 1, rejected: [] }));
    vi.stubGlobal('fetch', fetchMock);
    await createBatch([{ source: 'base64', content_b64: 'abc' }], 4, 'project-a');
    await getIngestJob('job', undefined, 'project-a');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).project_id).toBe('project-a');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/knowledge/ingest-jobs/job?project_id=project-a');
    await getIngestJob('public-job');
    expect(fetchMock.mock.calls[2][0]).toBe('/api/knowledge/ingest-jobs/public-job');
  });
});
