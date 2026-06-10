import { FileText, GitBranch, LayoutDashboard, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import type { RunDetailView } from "./types";
import { useTranslation } from "../../stores/i18n";

export function RunDetailTabs({
  activeView,
  onChange,
}: {
  activeView: RunDetailView;
  onChange: (view: RunDetailView) => void;
}) {
  const { t } = useTranslation();

  const runDetailViews: Array<{
    id: RunDetailView;
    label: string;
    icon: ReactNode;
  }> = [
    { id: "overview", label: t("runTabs.overview"), icon: <LayoutDashboard size={15} aria-hidden /> },
    { id: "report", label: t("runTabs.report"), icon: <FileText size={15} aria-hidden /> },
    { id: "agents", label: t("runTabs.agents"), icon: <GitBranch size={15} aria-hidden /> },
    { id: "quality", label: t("runTabs.quality"), icon: <ShieldCheck size={15} aria-hidden /> },
  ];

  return (
    <nav className="module-tabs run-detail-tabs" aria-label="Run detail sections">
      {runDetailViews.map((view) => (
        <button
          className={activeView === view.id ? "active" : ""}
          key={view.id}
          type="button"
          onClick={() => onChange(view.id)}
        >
          {view.icon}
          {view.label}
        </button>
      ))}
    </nav>
  );
}

