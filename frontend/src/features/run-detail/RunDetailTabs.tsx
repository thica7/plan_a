import { FileText, GitBranch, LayoutDashboard, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import type { RunDetailView } from "./types";

const runDetailViews: Array<{
  id: RunDetailView;
  label: string;
  icon: ReactNode;
}> = [
  { id: "overview", label: "Overview", icon: <LayoutDashboard size={15} aria-hidden /> },
  { id: "report", label: "Report", icon: <FileText size={15} aria-hidden /> },
  { id: "agents", label: "Agents", icon: <GitBranch size={15} aria-hidden /> },
  { id: "quality", label: "Quality", icon: <ShieldCheck size={15} aria-hidden /> },
];

export function RunDetailTabs({
  activeView,
  onChange,
}: {
  activeView: RunDetailView;
  onChange: (view: RunDetailView) => void;
}) {
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
