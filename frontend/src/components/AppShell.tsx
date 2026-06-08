import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  Briefcase,
  CheckCircle2,
  Database,
  FileText,
  History,
  Layers,
  PlusCircle,
  Radar,
  ShieldCheck,
} from "lucide-react";
import { getRuntime } from "../api/client";
import type { RuntimeConfig } from "../api/types";

interface AppShellProps {
  children: ReactNode;
}

const navItems = [
  { to: "/", label: "New run", icon: PlusCircle, end: true },
  { to: "/history", label: "Runs", icon: History },
  { to: "/enterprise", label: "Workbench", icon: Briefcase },
  { to: "/competitors", label: "Competitors", icon: Layers },
  { to: "/evidence", label: "Evidence", icon: Database },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/governance", label: "Governance", icon: ShieldCheck },
];

export function AppShell({ children }: AppShellProps) {
  const location = useLocation();
  const [runtime, setRuntime] = useState<RuntimeConfig | null>(null);

  useEffect(() => {
    let active = true;
    getRuntime()
      .then((value) => {
        if (active) setRuntime(value);
      })
      .catch(() => {
        if (active) setRuntime(null);
      });
    return () => {
      active = false;
    };
  }, []);

  const routeLabel = useMemo(() => routeTitle(location.pathname), [location.pathname]);
  const systemReady =
    runtime?.temporal_cutover_ready &&
    ((runtime.has_ark_api_key && runtime.has_ark_model) ||
      (runtime.has_backup_llm_api_key && runtime.has_backup_llm_model));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" to="/" aria-label="Competiscope home">
          <span className="brand-mark">
            <Radar size={18} aria-hidden />
          </span>
          <span>
            <strong>Competiscope</strong>
            <small>Enterprise CI</small>
          </span>
        </Link>

        <nav className="nav-list" aria-label="Primary">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink end={item.end} key={item.to} to={item.to}>
                <Icon size={17} aria-hidden />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        <div className="sidebar-system">
          <span className={systemReady ? "system-dot ready" : "system-dot warn"} />
          <div>
            <strong>{systemReady ? "Ready for real runs" : "Needs attention"}</strong>
            <small>
              {runtime?.temporal_cutover_ready ? "Temporal routed" : "Runtime unknown"}
            </small>
          </div>
        </div>
      </aside>

      <div className="content-shell">
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

        <main className="main-pane">{children}</main>
      </div>
    </div>
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

function routeTitle(pathname: string) {
  if (pathname === "/") return "Run setup";
  if (pathname.startsWith("/runs/")) return "Run detail";
  if (pathname.startsWith("/history")) return "Run history";
  if (pathname.startsWith("/competitors")) return "Competitor library";
  if (pathname.startsWith("/evidence")) return "Evidence center";
  if (pathname.startsWith("/reports")) return "Report studio";
  if (pathname.startsWith("/governance")) return "Governance";
  if (pathname.startsWith("/enterprise")) return "Enterprise workbench";
  return "Workspace";
}
