import { Link } from "react-router-dom";
import { Activity, AlertTriangle, CheckCircle2 } from "lucide-react";
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
      <div className="topbar-title">
        <span>{routeLabel}</span>
        <strong>{runtime?.default_execution_mode === "real" ? "Real mode" : "Demo mode"}</strong>
      </div>
      <div className="topbar-actions" aria-label="System status">
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
        <Link className="primary-link" to="/">
          <Activity size={15} aria-hidden />
          Run
        </Link>
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
