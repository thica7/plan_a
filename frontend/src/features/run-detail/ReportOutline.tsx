import { ChevronRight } from "lucide-react";
import { slugReportHeading } from "../report/ReportView";
import { useTranslation } from "../../stores/i18n";

export interface ReportOutlineItem {
  id: string;
  level: number;
  title: string;
}

export function ReportOutline({ markdown }: { markdown: string }) {
  const { t } = useTranslation();
  const items = buildReportOutline(markdown);

  return (
    <aside className="report-outline-panel">
      <div className="report-outline-heading">
        <strong>{t('reportDetail.outline')}</strong>
        <span>{items.length} sections</span>
      </div>
      {items.length > 0 ? (
        <nav aria-label={t('reportDetail.outline')}>
          {items.map((item) => (
            <a className={`level-${item.level}`} href={`#${item.id}`} key={`${item.id}-${item.title}`}>
              <ChevronRight size={13} aria-hidden />
              <span>{item.title}</span>
            </a>
          ))}
        </nav>
      ) : (
        <p>{t('reportDetail.noHeadings')}</p>
      )}
    </aside>
  );
}

export function buildReportOutline(markdown: string): ReportOutlineItem[] {
  return markdown
    .split(/\r?\n/)
    .map((line) => line.match(/^(#{1,4})\s+(.+)$/))
    .filter((match): match is RegExpMatchArray => Boolean(match))
    .map((match) => {
      const title = cleanHeading(match[2]);
      return {
        id: slugReportHeading(title),
        level: match[1].length,
        title,
      };
    })
    .filter((item) => item.title.length > 0)
    .slice(0, 36);
}

function cleanHeading(value: string) {
  return value
    .replace(/\[source:[^\]]+\]/g, "")
    .replace(/[`*_~]/g, "")
    .trim();
}
