import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useKnowledgeStore } from '../../stores/knowledgeStore';
import { useEnterpriseWorkbenchData } from './useEnterpriseWorkbenchData';

vi.mock('./dataLoaders', () => ({
  loadWorkbenchProjects: async () => ({ projects: [{ id: 'report-project', workspace_id: 'ws' }], notifications: [] }),
  loadProjectCore: async () => ({ artifacts: [], claims: [], competitors: [], evidence: [], notifications: [], versions: [] }),
  loadProjectSignals: async () => ({}),
  loadReleaseGate: async () => null,
}));
const initial = useKnowledgeStore.getState();
afterEach(() => { useKnowledgeStore.setState(initial, true); vi.unstubAllGlobals(); });

it('uses report project fallback and keeps a known public reference explicit despite another page scope', async () => {
  const rollbackResult = { matched_count: 1, rolled_back_count: 1, restored_count: 0, archived_document_ids: [], restored_document_ids: [], skipped_document_ids: [] };
  const fetchMock = vi.fn((input: RequestInfo | URL) => Promise.resolve({ ok: true, headers: new Headers(), json: async () => String(input).includes('/rollback') ? rollbackResult : [] }));
  vi.stubGlobal('fetch', fetchMock);
  useKnowledgeStore.getState().setProjectId('unrelated-page-project');
  const { result } = renderHook(() => useEnterpriseWorkbenchData('reports'));
  await waitFor(() => expect(result.current.selectedProject?.id).toBe('report-project'));
  await act(async () => { await result.current.handleKbRollbackIssue('unknown-legacy', { document_ids: ['doc'] }); });
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/rollback'))[0][0]).toBe('/api/knowledge/documents/rollback?project_id=report-project');
  await act(async () => { await result.current.handleKbRollbackIssue('known-public', { document_ids: ['public'], project_id: null }); });
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/rollback'))[1][0]).toBe('/api/knowledge/documents/rollback');
});
