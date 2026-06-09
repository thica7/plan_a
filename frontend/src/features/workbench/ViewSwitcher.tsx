import { Bell, Database, FileText, Gauge, Layers, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { ActionButton } from "../../components/interaction/ActionButton";
import { useTranslation } from "../../stores/i18n";
import type { EnterpriseView } from "./types";

const viewIcons: Record<EnterpriseView, ReactNode> = {
  overview: <Gauge size={15} aria-hidden />,
  evidence: <Database size={15} aria-hidden />,
  reports: <FileText size={15} aria-hidden />,
  competitors: <Layers size={15} aria-hidden />,
  governance: <ShieldCheck size={15} aria-hidden />,
  activity: <Bell size={15} aria-hidden />,
};

const viewKeys: Record<EnterpriseView, string> = {
  overview: "workbench.viewOverview",
  evidence: "workbench.viewEvidence",
  reports: "workbench.viewReports",
  competitors: "workbench.viewCompetitors",
  governance: "workbench.viewGovernance",
  activity: "workbench.viewActivity",
};

const viewOrder: EnterpriseView[] = ["overview", "evidence", "reports", "competitors", "governance", "activity"];

export function ViewSwitcher({
  activeView,
  onChange,
}: {
  activeView: EnterpriseView;
  onChange: (view: EnterpriseView) => void;
}) {
  const { t } = useTranslation();
  return (
    <nav className="module-tabs" aria-label={t('workbench.sections')}>
      {viewOrder.map((view) => (
        <ActionButton
          authenticity={{
            actionId: `workbench.view.${view}`,
            kind: "toggle",
            description: `switches workbench to the ${view} view`,
          }}
          className={view === activeView ? "active" : ""}
          key={view}
          onClick={() => onChange(view)}
        >
          {viewIcons[view]}
          {t(viewKeys[view])}
        </ActionButton>
      ))}
    </nav>
  );
}
