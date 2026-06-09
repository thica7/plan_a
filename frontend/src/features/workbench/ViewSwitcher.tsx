import { Bell, Database, FileText, Gauge, Layers, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import type { EnterpriseView } from "./types";

const viewItems: Array<{ id: EnterpriseView; label: string; icon: ReactNode }> = [
  { id: "overview", label: "Overview", icon: <Gauge size={15} aria-hidden /> },
  { id: "evidence", label: "Evidence", icon: <Database size={15} aria-hidden /> },
  { id: "reports", label: "Reports", icon: <FileText size={15} aria-hidden /> },
  { id: "competitors", label: "Competitors", icon: <Layers size={15} aria-hidden /> },
  { id: "governance", label: "Governance", icon: <ShieldCheck size={15} aria-hidden /> },
  { id: "activity", label: "Activity", icon: <Bell size={15} aria-hidden /> },
];

export function ViewSwitcher({
  activeView,
  onChange,
}: {
  activeView: EnterpriseView;
  onChange: (view: EnterpriseView) => void;
}) {
  return (
    <nav className="module-tabs" aria-label="Workbench sections">
      {viewItems.map((item) => (
        <button
          className={item.id === activeView ? "active" : ""}
          key={item.id}
          type="button"
          onClick={() => onChange(item.id)}
        >
          {item.icon}
          {item.label}
        </button>
      ))}
    </nav>
  );
}
