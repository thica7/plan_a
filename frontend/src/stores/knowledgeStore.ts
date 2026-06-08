import { create } from 'zustand';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface KnowledgeDocument {
  id: string;
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

interface KnowledgeState {
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
  fetchDocuments: () => Promise<void>;
  deleteDocument: (id: string) => Promise<void>;
  setFilter: (key: keyof KnowledgeState['filters'], value: string) => void;
  setPage: (page: number) => void;
  setPageSize: (pageSize: number) => void;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useKnowledgeStore = create<KnowledgeState>((set, get) => ({
  documents: [],
  loading: false,
  error: null,
  filters: { competitor: '', dimension: '', source_type: '' },
  page: 1,
  pageSize: 10,
  totalCount: 0,
  debounceTimer: null,
  errorTimer: null,

  fetchDocuments: async () => {
    set({ loading: true, error: null });
    try {
      const { filters, page, pageSize } = get();
      const params = new URLSearchParams();
      if (filters.competitor) params.set('competitor', filters.competitor);
      if (filters.dimension) params.set('dimension', filters.dimension);
      if (filters.source_type) params.set('source_type', filters.source_type);
      params.set('page', String(page));
      params.set('page_size', String(pageSize));

      const res = await fetch(`/api/knowledge/documents?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      
      const totalCountHeader = res.headers.get('X-Total-Count');
      const totalCount = totalCountHeader ? parseInt(totalCountHeader, 10) : data.length;

      set({ documents: data, totalCount, loading: false });
    } catch (err) {
      const errorMsg = String(err);
      set({ error: errorMsg, loading: false });
      const { errorTimer } = get();
      if (errorTimer) clearTimeout(errorTimer);
      const nextErrorTimer = setTimeout(() => {
        set({ error: null });
      }, 5000);
      set({ errorTimer: nextErrorTimer });
    }
  },

  deleteDocument: async (id: string) => {
    try {
      const res = await fetch(`/api/knowledge/documents/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      set((s) => ({ documents: s.documents.filter((d) => d.id !== id) }));
    } catch (err) {
      const errorMsg = String(err);
      set({ error: errorMsg });
      const { errorTimer } = get();
      if (errorTimer) clearTimeout(errorTimer);
      const nextErrorTimer = setTimeout(() => {
        set({ error: null });
      }, 5000);
      set({ errorTimer: nextErrorTimer });
    }
  },

  setFilter: (key, value) => {
    set((s) => ({ filters: { ...s.filters, [key]: value }, page: 1 }));
    const { debounceTimer } = get();
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
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
