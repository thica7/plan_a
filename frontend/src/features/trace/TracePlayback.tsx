import { ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import type { TraceSpan } from "../../api/types";
import { useTranslation } from "../../stores/i18n";
import { displayLabel, displayScope } from "../../i18n/display";

interface Props {
  spans: TraceSpan[];
}

export function TracePlayback({ spans }: Props) {
  const { locale, t } = useTranslation();
  const ordered = useMemo(() => spans.filter((span) => span.full_input || span.full_output), [spans]);
  const [index, setIndex] = useState(0);
  const activeIndex = Math.min(index, Math.max(ordered.length - 1, 0));
  const active = ordered[activeIndex];

  if (ordered.length === 0) {
    return (
      <section className="panel trace-playback-panel">
        <h2>{t('trace.playback')}</h2>
        <p>{t('trace.noReplayable')}</p>
      </section>
    );
  }

  return (
    <section className="panel trace-playback-panel">
      <div className="panel-heading-row">
        <h2>{t('trace.playback')}</h2>
        <span className="muted-text">{activeIndex + 1} / {ordered.length}</span>
      </div>
      <div className="playback-controls">
        <button
          aria-label={t('trace.previousSpan')}
          className="icon-button"
          disabled={activeIndex === 0}
          onClick={() => setIndex((value) => Math.max(0, value - 1))}
          type="button"
        >
          <ChevronLeft size={16} aria-hidden />
        </button>
        <input
          aria-label={t('trace.position')}
          max={ordered.length - 1}
          min={0}
          onChange={(event) => setIndex(Number(event.target.value))}
          type="range"
          value={activeIndex}
        />
        <button
          aria-label={t('trace.nextSpan')}
          className="icon-button"
          disabled={activeIndex >= ordered.length - 1}
          onClick={() => setIndex((value) => Math.min(ordered.length - 1, value + 1))}
          type="button"
        >
          <ChevronRight size={16} aria-hidden />
        </button>
      </div>
      <article className={`playback-card ${active.status}`}>
        <header>
          <strong>{displayLabel(active.agent, locale)}{active.subagent ? `/${displayScope(active.subagent, locale)}` : ""}</strong>
          <span className="playback-kind">{displayLabel(active.kind, locale)} / {displayLabel(active.name, locale)}</span>
          <code className={`playback-status ${active.status}`}>{displayLabel(active.status, locale)}</code>
        </header>
        <div className="playback-meta">
          <span>{active.duration_ms}{t('common.milliseconds')}</span>
          <span>{t('trace.input')} {active.input_tokens_estimate}</span>
          <span>{t('trace.output')} {active.output_tokens_estimate}</span>
          {active.provider ? <span>{active.provider}</span> : null}
        </div>
        <div className="playback-columns">
          <div>
            <h3>{t('trace.input')}</h3>
            <pre>{active.full_input || active.input_preview}</pre>
          </div>
          <div>
            <h3>{t('trace.output')}</h3>
            <pre>{active.full_output || active.output_preview}</pre>
          </div>
        </div>
      </article>
    </section>
  );
}
