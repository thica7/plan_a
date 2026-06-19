import { X } from 'lucide-react';
import { useTranslation } from '../../stores/i18n';

export interface RetrievalParams {
  dense_weight: number;
  sparse_weight: number;
  rerank_top_k: number;
  final_top_k: number;
  mmr_lambda: number;
  enable_query_rewrite: boolean;
  enable_rerank: boolean;
  enable_mmr: boolean;
}

export const DEFAULT_RETRIEVAL_PARAMS: RetrievalParams = {
  dense_weight: 1,
  sparse_weight: 1,
  rerank_top_k: 8,
  final_top_k: 8,
  mmr_lambda: 0,
  enable_query_rewrite: true,
  enable_rerank: true,
  enable_mmr: false,
};

interface RetrievalParamsDrawerProps {
  open: boolean;
  params: RetrievalParams;
  onChange: (params: RetrievalParams) => void;
  onClose: () => void;
}

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="grid gap-2 text-sm font-semibold">
      <span className="flex items-center justify-between gap-3">
        {label}
        <code className="rounded bg-base-200 px-2 py-1 text-xs">{value}</code>
      </span>
      <input
        type="range"
        className="range range-primary range-sm"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function ToggleRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-lg border border-base-300 bg-base-200/60 p-3 text-sm font-semibold">
      {label}
      <input
        type="checkbox"
        className="toggle toggle-primary"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
    </label>
  );
}

export function RetrievalParamsDrawer({ open, params, onChange, onClose }: RetrievalParamsDrawerProps) {
  const { t } = useTranslation();
  const update = (patch: Partial<RetrievalParams>) => onChange({ ...params, ...patch });

  return (
    <div className={`fixed inset-0 z-50 ${open ? '' : 'pointer-events-none'}`} aria-hidden={!open}>
      <div
        className={`absolute inset-0 bg-black/30 transition-opacity ${open ? 'opacity-100' : 'opacity-0'}`}
        onClick={onClose}
      />
      <aside className={`absolute right-0 top-0 h-full w-full max-w-md bg-base-100 shadow-2xl transition-transform ${open ? 'translate-x-0' : 'translate-x-full'}`}>
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b border-base-300 p-5">
            <div>
              <h2 className="text-lg font-bold">{t('retrieval.title')}</h2>
              <p className="text-xs text-base-content/60">Changes re-run the current search automatically.</p>
            </div>
            <button type="button" className="btn btn-ghost btn-sm btn-circle" onClick={onClose} aria-label="Close retrieval parameters">
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="grid flex-1 content-start gap-5 overflow-y-auto p-5">
            <SliderRow label={t('retrieval.denseWeight')} value={params.dense_weight} min={0} max={2} step={0.1} onChange={(value) => update({ dense_weight: value })} />
            <SliderRow label={t('retrieval.sparseWeight')} value={params.sparse_weight} min={0} max={2} step={0.1} onChange={(value) => update({ sparse_weight: value })} />
            <SliderRow label={t('retrieval.rerankTopK')} value={params.rerank_top_k} min={1} max={50} step={1} onChange={(value) => update({ rerank_top_k: value })} />
            <SliderRow label="Final top K" value={params.final_top_k} min={1} max={30} step={1} onChange={(value) => update({ final_top_k: value })} />
            <SliderRow label="MMR lambda" value={params.mmr_lambda} min={0} max={1} step={0.05} onChange={(value) => update({ mmr_lambda: value })} />

            <div className="grid gap-2">
              <ToggleRow label="Query rewrite" checked={params.enable_query_rewrite} onChange={(checked) => update({ enable_query_rewrite: checked })} />
              <ToggleRow label="Rerank" checked={params.enable_rerank} onChange={(checked) => update({ enable_rerank: checked })} />
              <ToggleRow label="MMR" checked={params.enable_mmr} onChange={(checked) => update({ enable_mmr: checked, mmr_lambda: checked ? params.mmr_lambda || 0.4 : 0 })} />
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
