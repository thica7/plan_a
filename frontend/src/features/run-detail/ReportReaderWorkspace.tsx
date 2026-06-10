import { FileSearch, GitCompareArrows, PanelRight } from "lucide-react";
import { useState, type KeyboardEvent } from "react";
import { useTranslation } from '../../stores/i18n';
import { ReportView } from "../report/ReportView";
import type { ReportSourceBundle } from "../report/sourceBundle";

export function ReportReaderWorkspace({
  activeSourceId,
  markdown,
  onActiveSourceChange,
  reportSources,
}: {
  activeSourceId: string | null;
  markdown: string;
  onActiveSourceChange: (sourceId: string | null) => void;
  reportSources: ReportSourceBundle;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");

  function handleFind(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" || !query.trim()) return;
    event.preventDefault();
    (window as Window & { find?: (value: string) => boolean }).find?.(query.trim());
  }

  return (
    <div className="report-reader-workspace">
      <div className="report-review-toolbar">
        <div className="report-mode-toggle" aria-label="Report reader mode">
          <button className="active" type="button">
            <PanelRight size={14} aria-hidden />
            {t('reportDetail.threePane')}
          </button>
          <button type="button">
            <GitCompareArrows size={14} aria-hidden />
            {t('reportDetail.compare')}
          </button>
        </div>
        <label className="report-find-control">
          <FileSearch size={14} aria-hidden />
          <input
            aria-label={t('reportDetail.findInReport')}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleFind}
            placeholder={t('reportDetail.findInReport')}
            type="search"
            value={query}
          />
        </label>
      </div>

      <ReportView
        activeSourceId={activeSourceId}
        layout="reader"
        markdown={markdown}
        onActiveSourceChange={onActiveSourceChange}
        readerTitle={t('reportDetail.finalReport')}
        showSourceTrace={false}
        sourceAliases={reportSources.aliases}
        sources={reportSources.sources}
      />
    </div>
  );
}
