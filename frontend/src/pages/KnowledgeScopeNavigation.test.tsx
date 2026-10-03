import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import KnowledgePage from './KnowledgePage';
import { VersionDrawer } from '../features/version/VersionDrawer';
import { UploadDrawer } from '../features/upload/UploadDrawer';
import { useKnowledgeStore, type KnowledgeDocument } from '../stores/knowledgeStore';
import { useI18n } from '../stores/i18n';

const initial = useKnowledgeStore.getState();
function response(body: unknown) {
  return { ok: true, status: 200, headers: new Headers({ 'X-Total-Count': '0' }), json: async () => body };
}
function document(id = 'doc', projectId: string | null = 'project-a'): KnowledgeDocument {
  return { id, title: `Title ${id}`, url: null, source_type: 'manual', competitor: null, dimension: null, content_hash: 'hash', text: `Body ${id}`, markdown: '', status: 'active', fetched_at: '2026-10-01', indexed_at: null, metadata: {}, workspace_id: 'ws', project_id: projectId };
}
beforeEach(() => useI18n.getState().setLocale('en-US'));
afterEach(() => {
  const state = useKnowledgeStore.getState();
  if (state.errorTimer) clearTimeout(state.errorTimer);
  if (state.debounceTimer) clearTimeout(state.debounceTimer);
  useKnowledgeStore.setState(initial, true);
  vi.unstubAllGlobals();
});

describe('knowledge project navigation', () => {
  it('uses the deep-link project for list, detail and chunks, and typed public scope for writes', async () => {
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input); calls.push(url);
      if (url.includes('/chunks')) return Promise.resolve(response([]));
      if (url.includes('/rollback')) return Promise.resolve(response({ matched_count: 0, archived_document_ids: [], restored_document_ids: [], skipped_document_ids: [] }));
      if (url.includes('/documents/doc')) return Promise.resolve(response(document('doc', null)));
      return Promise.resolve(response([]));
    }));
    render(<MemoryRouter initialEntries={['/knowledge?document_id=doc&project_id=project-a']}><KnowledgePage /></MemoryRouter>);
    await screen.findAllByText('Title doc');
    await waitFor(() => expect(calls).toContain('/api/knowledge/documents/doc/chunks?project_id=project-a'));
    expect(calls).toContain('/api/knowledge/documents?project_id=project-a&limit=10&offset=0');
    expect(calls).toContain('/api/knowledge/documents/doc?project_id=project-a');
    fireEvent.click(screen.getByRole('button', { name: 'Rollback document', hidden: true }));
    await waitFor(() => expect(calls).toContain('/api/knowledge/documents/rollback'));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(calls).toContain('/api/knowledge/documents/doc'));
    expect(calls).not.toContain('/api/knowledge/documents/rollback?project_id=project-a');
  });

  it('clears selected content on navigation and ignores an old project detail response', async () => {
    let navigate!: ReturnType<typeof useNavigate>;
    function Host() { navigate = useNavigate(); return <KnowledgePage />; }
    let finishOld!: (value: unknown) => void;
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/knowledge/documents/old')) return new Promise((resolve) => { finishOld = resolve; });
      if (url.startsWith('/api/knowledge/documents/new') && !url.includes('/chunks')) return Promise.resolve(response(document('new', null)));
      return Promise.resolve(response([]));
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<MemoryRouter initialEntries={['/knowledge?document_id=old&project_id=project-a']}><Host /></MemoryRouter>);
    await waitFor(() => expect(finishOld).toBeDefined());
    act(() => navigate('/knowledge?document_id=new'));
    await screen.findAllByText('Title new');
    await act(async () => { finishOld(response(document('old'))); });
    expect(screen.queryByText('Title old')).not.toBeInTheDocument();
    expect(useKnowledgeStore.getState().projectId).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/knowledge/documents?limit=10&offset=0')).toBe(true);
  });

  it.each(['project-a', null])('sends %s scope through version list, two-id diff and merge', async (projectId) => {
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input); calls.push(url);
      if (url.includes('/versions')) return Promise.resolve(response([{ ...document('doc'), version: 2, is_active: true }, { ...document('old'), version: 1 }]));
      if (url.includes('/diff')) return Promise.resolve(response({ document_id: 'doc', against: 'old', diff: [] }));
      return Promise.resolve(response(document()));
    }));
    const onMerged = vi.fn();
    render(<VersionDrawer documentId="doc" projectId={projectId} onMerged={onMerged} />);
    await waitFor(() => expect(calls.some((url) => url.includes('/diff?'))).toBe(true));
    expect(calls).toContain(`/api/knowledge/documents/doc/versions${projectId ? '?project_id=project-a' : ''}`);
    expect(calls).toContain(`/api/knowledge/documents/doc/diff?against=old${projectId ? '&project_id=project-a' : ''}`);
    fireEvent.click(screen.getByRole('button', { name: /merge selected/i }));
    await waitFor(() => expect(onMerged).toHaveBeenCalled());
    expect(calls).toContain(`/api/knowledge/documents/doc/merge${projectId ? '?project_id=project-a' : ''}`);
  });

  it('clears old detail and selector fields and ignores late chunks when switching projects', async () => {
    let navigate!: ReturnType<typeof useNavigate>;
    function Host() { navigate = useNavigate(); return <KnowledgePage />; }
    let finishChunks!: (value: unknown) => void;
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/old/chunks')) return new Promise((resolve) => { finishChunks = resolve; });
      if (url.includes('/documents/old')) return Promise.resolve(response(document('old')));
      if (url.startsWith('/api/knowledge/documents?') && url.includes('project-b')) return Promise.resolve(response([document('new', 'project-b')]));
      return Promise.resolve(response([]));
    }));
    render(<MemoryRouter initialEntries={['/knowledge?document_id=old&raw_source_id=old-raw&project_id=project-a']}><Host /></MemoryRouter>);
    await waitFor(() => expect(finishChunks).toBeDefined());
    expect(screen.getByLabelText('Raw source ID')).toHaveValue('old-raw');
    act(() => navigate('/knowledge?project_id=project-b'));
    await screen.findByText('Title new');
    await act(async () => { finishChunks(response([{ id: 'old-chunk', text: 'Old project chunk' }])); });
    expect(screen.queryByText('Title old')).not.toBeInTheDocument();
    expect(screen.queryByText('Old project chunk')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Raw source ID')).toHaveValue('');
    expect(screen.queryByRole('button', { name: 'Rollback document', hidden: true })).not.toBeInTheDocument();
  });

  it('polls an upload with its creation project after the page project changes', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      return Promise.resolve(response(url.endsWith('/batch') ? { job_id: 'job', accepted: 1, rejected: [] } : { status: 'success', completed_items: 1, failed_items: 0, failed: [], results: [] }));
    });
    vi.stubGlobal('fetch', fetchMock);
    const complete = vi.fn();
    const { container, rerender } = render(<UploadDrawer open projectId="project-a" onClose={() => {}} onComplete={complete} />);
    fireEvent.change(container.querySelector('input[type=file]')!, { target: { files: [new File(['facts'], 'facts.txt', { type: 'text/plain' })] } });
    fireEvent.click(screen.getByRole('button', { name: /start upload/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    rerender(<UploadDrawer open projectId="project-b" onClose={() => {}} onComplete={complete} />);
    await waitFor(() => expect(complete).toHaveBeenCalled(), { timeout: 2000 });
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body)).project_id).toBe('project-a');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/knowledge/ingest-jobs/job?project_id=project-a');
  });
});
