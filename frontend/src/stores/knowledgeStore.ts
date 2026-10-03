import { apiFetch } from "../api/http";
import { knowledgeProjectUrl } from "../api/knowledge";
import { create } from 'zustand';

export interface KnowledgeDocument {
  id: string;
  workspace_id?: string | null;
  project_id?: string | null;
  url: string | null;
  title: string;
  source_type: string;
  competitor: string | null;
  dimension: string | null;
  content_hash: string;
  text: string;
  markdown: string;
  status: string;
  fetched_at: string;
  indexed_at: string | null;
  metadata: Record<string, unknown>;
}

export interface KnowledgeChunk {
  id: string;
  document_id: string;
  chunk_index: number;
  text: string;
  token_count: number;
  embedding_model: string;
  content_hash: string;
  crawl_run_id?: string | null;
  metadata: Record<string, unknown>;
}

export interface KnowledgeRollbackRequest {
  project_id?: string | null;
  document_ids?: string[];
  run_id?: string | null;
  raw_source_id?: string | null;
  crawl_run_id?: string | null;
  restore_previous?: boolean;
}

export interface KnowledgeRollbackResult {
  matched_count: number;
  rolled_back_count: number;
  restored_count: number;
  archived_document_ids: string[];
  restored_document_ids: string[];
  skipped_document_ids: string[];
  vector_cleanup_error?: string | null;
}

interface KnowledgeState {
  projectId: string | null;
  scopeRevision: number;
  setProjectId: (projectId: string | null) => void;
  documents: KnowledgeDocument[];
  loading: boolean;
  error: string | null;
  filters: {
    competitor: string;
    dimension: string;
    source_type: string;
  };
  page: number;
  pageSize: number;
  totalCount: number;
  debounceTimer: ReturnType<typeof setTimeout> | null;
  errorTimer: ReturnType<typeof setTimeout> | null;
  rollbackLoading: boolean;
  rollbackResult: KnowledgeRollbackResult | null;
  fetchDocuments: () => Promise<void>;
  deleteDocument: (id: string, projectId?: string | null) => Promise<void>;
  rollbackDocuments: (request: KnowledgeRollbackRequest) => Promise<KnowledgeRollbackResult>;
  setFilter: (key: keyof KnowledgeState['filters'], value: string) => void;
  setPage: (page: number) => void;
  setPageSize: (pageSize: number) => void;
}

function scheduleTransientError(set: (state: Partial<KnowledgeState>) => void, get: () => KnowledgeState) {
  const { errorTimer } = get();
  if (errorTimer) clearTimeout(errorTimer);
  const nextErrorTimer = setTimeout(() => {
    set({ error: null });
  }, 5000);
  set({ errorTimer: nextErrorTimer });
}

function compactRollbackRequest(request: KnowledgeRollbackRequest) {
  return {
    document_ids: request.document_ids?.filter(Boolean) ?? [],
    run_id: request.run_id?.trim() || null,
    raw_source_id: request.raw_source_id?.trim() || null,
    crawl_run_id: request.crawl_run_id?.trim() || null,
    restore_previous: request.restore_previous ?? true,
  };
}

export const useKnowledgeStore = create<KnowledgeState>((set, get) => ({
  projectId: null,
  scopeRevision: 0,
  setProjectId: (projectId) => {
    if (get().projectId === projectId) return;
    const { debounceTimer } = get();
    if (debounceTimer) clearTimeout(debounceTimer);
    set((state) => ({ projectId, scopeRevision: state.scopeRevision + 1, documents: [], totalCount: 0,
      page: 1, loading: false, error: null, rollbackLoading: false, rollbackResult: null, debounceTimer: null }));
  },
  documents: [],
  loading: false,
  error: null,
  filters: { competitor: '', dimension: '', source_type: '' },
  page: 1,
  pageSize: 10,
  totalCount: 0,
  debounceTimer: null,
  errorTimer: null,
  rollbackLoading: false,
  rollbackResult: null,

  fetchDocuments: async () => {
    const { projectId, scopeRevision, filters, page, pageSize } = get();
    const isCurrent = () => get().scopeRevision === scopeRevision && get().projectId === projectId;
    set({ loading: true, error: null });
    try {
      const params = new URLSearchParams();
      if (projectId) params.set('project_id', projectId);
      if (filters.competitor) params.set('competitor', filters.competitor);
      if (filters.dimension) params.set('dimension', filters.dimension);
      if (filters.source_type) params.set('source_type', filters.source_type);
      params.set('limit', String(pageSize));
      params.set('offset', String((page - 1) * pageSize));

      const res = await apiFetch(`/api/knowledge/documents?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const totalCountHeader = res.headers.get('X-Total-Count');
      const totalCount = totalCountHeader ? parseInt(totalCountHeader, 10) : data.length;

      if (isCurrent()) set({ documents: data, totalCount, loading: false });
    } catch (err) {
      if (!isCurrent()) return;
      set({ error: String(err), loading: false });
      scheduleTransientError(set, get);
    }
  },

  deleteDocument: async (id: string, projectId?: string | null) => {
    const scopeProjectId = projectId === undefined ? get().projectId : projectId;
    const revision = get().scopeRevision;
    try {
      const res = await apiFetch(knowledgeProjectUrl(`/api/knowledge/documents/${id}`, scopeProjectId), { method: 'DELETE' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      if (get().scopeRevision === revision) set((s) => ({ documents: s.documents.filter((d) => d.id !== id) }));
    } catch (err) {
      if (get().scopeRevision !== revision) return;
      set({ error: String(err) });
      scheduleTransientError(set, get);
    }
  },

  rollbackDocuments: async (request: KnowledgeRollbackRequest) => {
    const projectId = request.project_id === undefined ? get().projectId : request.project_id;
    const revision = get().scopeRevision;
    const payload = compactRollbackRequest(request);
    if (
      payload.document_ids.length === 0 &&
      !payload.run_id &&
      !payload.raw_source_id &&
      !payload.crawl_run_id
    ) {
      throw new Error('At least one rollback selector is required');
    }

    set({ rollbackLoading: true, rollbackResult: null, error: null });
    try {
      const res = await apiFetch(knowledgeProjectUrl('/api/knowledge/documents/rollback', projectId), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const result = (await res.json()) as KnowledgeRollbackResult;
      if (get().scopeRevision === revision) {
        set({ rollbackResult: result, rollbackLoading: false });
        await get().fetchDocuments();
      }
      return result;
    } catch (err) {
      if (get().scopeRevision === revision) {
        set({ error: String(err), rollbackLoading: false });
        scheduleTransientError(set, get);
      }
      throw err;
    }
  },

  setFilter: (key, value) => {
    set((s) => ({ filters: { ...s.filters, [key]: value }, page: 1 }));
    const { debounceTimer } = get();
    if (debounceTimer) clearTimeout(debounceTimer);
    const nextDebounceTimer = setTimeout(() => {
      get().fetchDocuments();
    }, 300);
    set({ debounceTimer: nextDebounceTimer });
  },

  setPage: (page) => {
    set({ page });
    get().fetchDocuments();
  },

  setPageSize: (pageSize) => {
    set({ pageSize, page: 1 });
    get().fetchDocuments();
  },
}));
