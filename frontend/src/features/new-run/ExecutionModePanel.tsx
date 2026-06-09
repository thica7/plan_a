import { CalendarClock, KeyRound, Zap } from "lucide-react";
import { useTranslation } from "../../stores/i18n";
import { SectionHeading } from "./SectionHeading";
import type { ExecutionMode } from "./types";

interface ExecutionModePanelProps {
  executionMode: ExecutionMode;
  setExecutionMode: (mode: ExecutionMode) => void;
}

export function ExecutionModePanel({
  executionMode,
  setExecutionMode,
}: ExecutionModePanelProps) {
  const { t } = useTranslation();
  return (
    <section className="form-section execution-section">
      <SectionHeading
        icon={<Zap size={17} aria-hidden />}
        index="06"
        meta={t('newRun.executionModeDesc')}
        title={t('newRun.executionMode')}
      />
      <div className="execution-mode-grid" role="radiogroup" aria-label={t('newRun.executionMode')}>
        <button
          className={executionMode === "real" ? "execution-mode-card active" : "execution-mode-card"}
          onClick={() => setExecutionMode("real")}
          type="button"
        >
          <KeyRound size={18} aria-hidden />
          <span>
            <strong>{t('newRun.realtimeApi')}</strong>
            <em>{t('newRun.realtimeDesc')}</em>
          </span>
          <i aria-hidden />
        </button>
        <button
          className={executionMode === "demo" ? "execution-mode-card active" : "execution-mode-card"}
          onClick={() => setExecutionMode("demo")}
          type="button"
        >
          <CalendarClock size={18} aria-hidden />
          <span>
            <strong>{t('newRun.demoMode')}</strong>
            <em>{t('newRun.demoDesc')}</em>
          </span>
          <i aria-hidden />
        </button>
      </div>
    </section>
  );
}
