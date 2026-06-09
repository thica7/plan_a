import { create } from 'zustand';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RetrievalHit {
  chunk_id: string;
  document_id: string;
  text: string;
  score: number;
  rerank_score: number | null;
  url: string | null;
  title: string;
  competitor: string | null;
  dimension: string | null;
  source_type: string;
}

interface SearchState {
  query: string;
  hits: RetrievalHit[];
  loading: boolean;
  error: string | null;
  competitors: string[];
  dimensions: string[];
  searchHistory: string[];
  setQuery: (q: string) => void;
  setCompetitors: (comps: string[]) => void;
  setDimensions: (dims: string[]) => void;
  search: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

let searchAbortController: AbortController | null = null;

const getInitialHistory = (): string[] => {
  try {
    const saved = sessionStorage.getItem('search_history');
    return saved ? JSON.parse(saved) : [];
  } catch {
    return [];
  }
};

export const useSearchStore = create<SearchState>((set, get) => ({
  query: '',
  hits: [],
  loading: false,
  error: null,
  competitors: [],
  dimensions: [],
  searchHistory: getInitialHistory(),

  setQuery: (q) => set({ query: q }),
  setCompetitors: (competitors) => set({ competitors }),
  setDimensions: (dimensions) => set({ dimensions }),

  search: async () => {
    const { query, competitors, dimensions, searchHistory } = get();
    const trimmedQuery = query.trim();
    if (!trimmedQuery) {
      set({ error: null, hits: [] });
      return;
    }

    if (searchAbortController) {
      searchAbortController.abort();
    }
    searchAbortController = new AbortController();
    const { signal } = searchAbortController;

    set({ loading: true, error: null });
    try {
      const res = await fetch('/api/knowledge/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: trimmedQuery,
          competitors,
          dimensions,
          top_k: 20,
          rerank_top_k: 8,
          mode: 'hybrid'
        }),
        signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      const nextHistory = [
        trimmedQuery,
        ...searchHistory.filter((q) => q !== trimmedQuery),
      ].slice(0, 5);

      try {
        sessionStorage.setItem('search_history', JSON.stringify(nextHistory));
      } catch (e) {
        console.warn('Failed to save search history to sessionStorage', e);
      }

      set({
        hits: data.hits ?? [],
        searchHistory: nextHistory,
        loading: false
      });
    } catch (err: any) {
      if (err.name === 'AbortError') {
        return;
      }
      set({ error: String(err), loading: false });
    }
  },
}));
