import { ChangeEvent, FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { BarChart3, SlidersHorizontal, Upload } from 'lucide-react';
import { useSearchStore, type RetrievalHit } from '../stores/searchStore';
import { SourceCard } from '../components/SourceCard';
import {
  DEFAULT_RETRIEVAL_PARAMS,
  RetrievalParamsDrawer,
  type RetrievalParams,
} from '../features/retrieval/RetrievalParamsDrawer';
import { useTranslation } from '../stores/i18n';

const PARAMS_STORAGE_KEY = 'retrieval_params';

interface EvalRunSummary {
  id: string;
  created_at: string;
  top_k: number;
  metrics: Record<string, number>;
}

interface EvalRunDetail extends EvalRunSummary {
  labels: Array<Record<string, unknown>>;
  results: Array<Record<string, unknown>>;
}

interface EvalLabel {
  query: string;
  relevant_doc_ids: string[];
  relevant_chunk_ids?: string[];
}

function highlightText(text: string, query: string): ReactNode[] {
  if (!query.trim()) return [text];
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'));
  return parts.map((part, i) =>
    part.toLowerCase() === query.toLowerCase() ? <mark key={i}>{part}</mark> : part
  );
}

function loadParams(): RetrievalParams {
  try {
    const saved = localStorage.getItem(PARAMS_STORAGE_KEY);
    return saved ? { ...DEFAULT_RETRIEVAL_PARAMS, ...JSON.parse(saved) } : DEFAULT_RETRIEVAL_PARAMS;
  } catch {
    return DEFAULT_RETRIEVAL_PARAMS;
  }
}

function parseJsonl(text: string): EvalLabel[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parsed = JSON.parse(line) as Partial<EvalLabel>;
      return {
        query: String(parsed.query ?? ''),
        relevant_doc_ids: Array.isArray(parsed.relevant_doc_ids) ? parsed.relevant_doc_ids.map(String) : [],
        relevant_chunk_ids: Array.isArray(parsed.relevant_chunk_ids) ? parsed.relevant_chunk_ids.map(String) : [],
      };
    })
    .filter((label) => label.query && (label.relevant_doc_ids.length > 0 || (label.relevant_chunk_ids?.length ?? 0) > 0));
}

function metricValue(metrics: Record<string, number>, names: string[]) {
  for (const name of names) {
    if (typeof metrics[name] === 'number') return metrics[name];
  }
  return 0;
}

function Sparkline({ values }: { values: number[] }) {
  const points = values.length > 0 ? values : [0];
  const path = points
    .map((value, index) => {
      const x = points.length === 1 ? 48 : (index / (points.length - 1)) * 96;
      const y = 28 - Math.max(0, Math.min(1, value)) * 24;
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');
  return (
    <svg className="h-8 w-28" viewBox="0 0 100 32" role="img" aria-label="Metric trend">
      <path d={path} fill="none" stroke="currentColor" strokeWidth="2" className="text-primary" />
    </svg>
  );
}

async function fileText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error('Unable to read eval file'));
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.readAsText(file);
  });
}

export default function SearchPage() {
  const { t } = useTranslation();
  const {
    query,
    competitors,
    dimensions,
    searchHistory,
    setQuery,
    setCompetitors,
    setDimensions,
  } = useSearchStore();

  const [hits, setHits] = useState<RetrievalHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState(searchHistory);
  const [showFilters, setShowFilters] = useState(false);
  const [paramsOpen, setParamsOpen] = useState(false);
  const [params, setParams] = useState<RetrievalParams>(() => loadParams());
  const [compInput, setCompInput] = useState('');
  const [dimInput, setDimInput] = useState('');
  const [evalLabels, setEvalLabels] = useState<EvalLabel[]>([]);
  const [evalRuns, setEvalRuns] = useState<EvalRunSummary[]>([]);
  const [evalResult, setEvalResult] = useState<EvalRunDetail | null>(null);
  const [evalError, setEvalError] = useState<string | null>(null);
  const [evalLoading, setEvalLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const runSearch = async (nextQuery = query, nextParams = params) => {
    const trimmedQuery = nextQuery.trim();
    if (!trimmedQuery) {
      setHits([]);
      setError(null);
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);

    try {
      const res = await fetch('/api/knowledge/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: trimmedQuery,
          competitors,
          dimensions,
          top_k: Math.max(nextParams.rerank_top_k, nextParams.final_top_k, 20),
          rerank_top_k: nextParams.enable_rerank ? nextParams.rerank_top_k : 0,
          final_top_k: nextParams.final_top_k,
          dense_weight: nextParams.dense_weight,
          sparse_weight: nextParams.sparse_weight,
          mmr_lambda: nextParams.enable_mmr ? nextParams.mmr_lambda : 0,
          enable_query_rewrite: nextParams.enable_query_rewrite,
          mode: nextParams.sparse_weight > 0 ? 'hybrid' : 'dense',
        }),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as { hits?: RetrievalHit[] };
      const nextHistory = [
        trimmedQuery,
        ...history.filter((item) => item !== trimmedQuery),
      ].slice(0, 5);
      sessionStorage.setItem('search_history', JSON.stringify(nextHistory));
      setHistory(nextHistory);
      setHits(data.hits ?? []);
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    localStorage.setItem(PARAMS_STORAGE_KEY, JSON.stringify(params));
    if (!query.trim()) return;
    const timer = window.setTimeout(() => {
      void runSearch(query, params);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [params]);

  useEffect(() => {
    void fetch('/api/knowledge/eval/runs')
      .then((res) => res.ok ? res.json() : [])
      .then((data) => setEvalRuns(Array.isArray(data) ? data : []))
      .catch(() => setEvalRuns([]));
  }, []);

  const handleSearch = (e: FormEvent) => {
    e.preventDefault();
    void runSearch();
  };

  const addCompetitor = () => {
    if (compInput.trim() && !competitors.includes(compInput.trim())) {
      setCompetitors([...competitors, compInput.trim()]);
      setCompInput('');
    }
  };

  const addDimension = () => {
    if (dimInput.trim() && !dimensions.includes(dimInput.trim())) {
      setDimensions([...dimensions, dimInput.trim()]);
      setDimInput('');
    }
  };

  const handleEvalFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      setEvalError(null);
      setEvalLabels(parseJsonl(await fileText(file)));
    } catch (err) {
      setEvalError(err instanceof Error ? err.message : String(err));
    } finally {
      event.target.value = '';
    }
  };

  const runEval = async () => {
    if (evalLabels.length === 0) return;
    setEvalLoading(true);
    setEvalError(null);
    try {
      const res = await fetch('/api/knowledge/eval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ labels: evalLabels, top_k: params.final_top_k }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as EvalRunDetail;
      setEvalResult(data);
      setEvalRuns((current) => [data, ...current.filter((run) => run.id !== data.id)].slice(0, 20));
    } catch (err) {
      setEvalError(err instanceof Error ? err.message : String(err));
    } finally {
      setEvalLoading(false);
    }
  };

  const activeMetrics = evalResult?.metrics ?? evalRuns[0]?.metrics ?? {};
  const recallValues = useMemo(() => evalRuns.slice(0, 10).reverse().map((run) => metricValue(run.metrics, ['recall@k', 'recall_at_k', `recall@${run.top_k}`])), [evalRuns]);

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{t('search.title')}</h1>
        <button type="button" className="btn btn-outline btn-sm gap-1" onClick={() => setParamsOpen(true)}>
          <SlidersHorizontal className="h-4 w-4" />
          {t('search.retrieval')}
        </button>
      </div>

      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          className="input input-bordered flex-1"
          placeholder={t('search.placeholder')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className="btn btn-primary" type="submit" disabled={loading}>
          {loading ? `${t('trace.search')}...` : t('trace.search')}
        </button>
        <button
          type="button"
          className={`btn btn-outline btn-sm ${showFilters ? 'btn-active' : ''}`}
          onClick={() => setShowFilters(!showFilters)}
        >
          {t('search.filters')}
        </button>
      </form>

      {showFilters && (
        <div className="card bg-base-200 p-4 space-y-3">
          <div className="flex gap-2 items-center">
            <input
              className="input input-bordered input-sm flex-1"
              placeholder={t('search.addCompetitor')}
              value={compInput}
              onChange={(e) => setCompInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addCompetitor())}
            />
            <button type="button" className="btn btn-sm" onClick={addCompetitor}>{t('common.add')}</button>
          </div>
          <div className="flex flex-wrap gap-1">
            {competitors.map((c) => (
              <span key={c} className="badge badge-primary gap-1">
                {c}
                <button onClick={() => setCompetitors(competitors.filter((x) => x !== c))}>x</button>
              </span>
            ))}
          </div>
          <div className="flex gap-2 items-center">
            <input
              className="input input-bordered input-sm flex-1"
              placeholder={t('search.addDimension')}
              value={dimInput}
              onChange={(e) => setDimInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addDimension())}
            />
            <button type="button" className="btn btn-sm" onClick={addDimension}>{t('common.add')}</button>
          </div>
          <div className="flex flex-wrap gap-1">
            {dimensions.map((d) => (
              <span key={d} className="badge badge-accent gap-1">
                {d}
                <button onClick={() => setDimensions(dimensions.filter((x) => x !== d))}>x</button>
              </span>
            ))}
          </div>
        </div>
      )}

      {history.length > 0 && (
        <div className="flex flex-wrap gap-2 items-center">
          <span className="text-xs text-base-content/50">{t('search.recent')}</span>
          {history.map((h) => (
            <button
              key={h}
              className="badge badge-ghost badge-sm cursor-pointer hover:badge-primary"
              onClick={() => { setQuery(h); void runSearch(h); }}
            >
              {h}
            </button>
          ))}
        </div>
      )}

      {error && <div className="alert alert-error">{error}</div>}

      <section className="rounded-lg border border-base-300 bg-base-100 p-4">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-primary" />
            <h2 className="font-bold">{t('search.retrievalEvaluation')}</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            <label className="btn btn-outline btn-sm gap-1">
              <Upload className="h-3.5 w-3.5" />
              JSONL
              <input className="hidden" type="file" accept=".jsonl,.json" onChange={handleEvalFile} />
            </label>
            <button type="button" className="btn btn-primary btn-sm" disabled={evalLoading || evalLabels.length === 0} onClick={runEval}>
              {evalLoading ? `${t('common.running')}...` : t('search.runEval')}
            </button>
          </div>
        </div>
        {evalError && <div className="alert alert-error mb-3 text-sm">{evalError}</div>}
        <div className="grid gap-3 sm:grid-cols-4">
          <div className="rounded-lg bg-base-200 p-3">
            <span className="text-xs text-base-content/55">{t('search.labels')}</span>
            <strong className="block text-lg">{evalLabels.length}</strong>
          </div>
          <div className="rounded-lg bg-base-200 p-3">
            <span className="text-xs text-base-content/55">Recall@k</span>
            <strong className="block text-lg">{metricValue(activeMetrics, ['recall@k', 'recall_at_k', `recall@${evalResult?.top_k ?? evalRuns[0]?.top_k ?? params.final_top_k}`]).toFixed(3)}</strong>
          </div>
          <div className="rounded-lg bg-base-200 p-3">
            <span className="text-xs text-base-content/55">MRR</span>
            <strong className="block text-lg">{metricValue(activeMetrics, ['mrr', 'MRR']).toFixed(3)}</strong>
          </div>
          <div className="rounded-lg bg-base-200 p-3">
            <span className="text-xs text-base-content/55">nDCG@k</span>
            <strong className="block text-lg">{metricValue(activeMetrics, ['ndcg@k', 'ndcg_at_k', `ndcg@${evalResult?.top_k ?? evalRuns[0]?.top_k ?? params.final_top_k}`]).toFixed(3)}</strong>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-base-content/60">
          <Sparkline values={recallValues} />
          <span>{evalRuns.length} {t('search.recentEvalRuns')}</span>
          {evalRuns.slice(0, 3).map((run) => (
            <code key={run.id} className="rounded bg-base-200 px-2 py-1">
              {new Date(run.created_at).toLocaleString()} k={run.top_k}
            </code>
          ))}
        </div>
      </section>

      <div className="space-y-3">
        {hits.map((hit) => (
          <div key={hit.chunk_id} className="card bg-base-200 p-4 space-y-2">
            <SourceCard
              title={hit.title}
              url={hit.url}
              competitor={hit.competitor}
              dimension={hit.dimension}
              source_type={hit.source_type}
              score={hit.score}
              rerank_score={hit.rerank_score}
            />
            <p className="text-xs text-base-content/70 line-clamp-3">
              {highlightText(hit.text.slice(0, 300), query)}
            </p>
          </div>
        ))}
        {!loading && hits.length === 0 && query && (
          <p className="text-base-content/50 text-center py-12">{t('search.noResults')}</p>
        )}
      </div>

      <RetrievalParamsDrawer
        open={paramsOpen}
        params={params}
        onChange={setParams}
        onClose={() => setParamsOpen(false)}
      />
    </div>
  );
}
