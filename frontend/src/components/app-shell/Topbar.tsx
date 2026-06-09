import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  Bell,
  CheckCircle2,
  ChevronDown,
  HelpCircle,
  Menu,
  Network,
} from "lucide-react";
import type { RuntimeConfig } from "../../api/types";

export function Topbar({
  routeLabel,
  runtime,
}: {
  routeLabel: string;
  runtime: RuntimeConfig | null;
}) {
  return (
    <header className="topbar">
      <div className="topbar-context">
        <button className="topbar-menu-button" type="button" aria-label="Open navigation">
          <Menu size={18} aria-hidden />
        </button>
        <button className="workspace-switcher" type="button">
          <span>Acme Corp</span>
          <ChevronDown size={15} aria-hidden />
        </button>
        <span className="topbar-divider" aria-hidden />
        <div className="topbar-title">
          <span>{routeLabel}</span>
          <strong>
            <Network size={15} aria-hidden />
            AI Competitive Intel
          </strong>
        </div>
      </div>
      <div className="topbar-actions" aria-label="System status">
        <Link className="primary-link topbar-research-link" to="/">
          <Activity size={15} aria-hidden />
          AI Research
        </Link>
        <StatusBadge
          good={Boolean(runtime?.temporal_cutover_ready)}
          label="Temporal"
        />
        <StatusBadge
          good={Boolean(runtime?.has_web_search_key)}
          label={runtime?.web_search_provider ?? "Search"}
        />
        <StatusBadge
          good={Boolean(runtime?.compliance_redaction_enabled)}
          label="Compliance"
        />
        <button className="topbar-icon-button" type="button" aria-label="Notifications">
          <Bell size={17} aria-hidden />
          <i aria-hidden />
        </button>
        <button className="topbar-icon-button" type="button" aria-label="Help">
          <HelpCircle size={17} aria-hidden />
        </button>
        <div className="topbar-user">
          <span className="avatar">AC</span>
          <strong>Acme Admin</strong>
          <ChevronDown size={14} aria-hidden />
        </div>
      </div>
    </header>
  );
}

function StatusBadge({ good, label }: { good: boolean; label: string }) {
  return (
    <span className={good ? "status-badge good" : "status-badge warn"}>
      {good ? <CheckCircle2 size={14} aria-hidden /> : <AlertTriangle size={14} aria-hidden />}
      {label}
    </span>
  );
}
