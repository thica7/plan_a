import { Link, NavLink } from "react-router-dom";
import { Radar } from "lucide-react";
import { navItems } from "./nav";

export function Sidebar({
  systemReady,
  temporalRouted,
}: {
  systemReady: boolean;
  temporalRouted: boolean;
}) {
  return (
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
          <small>{temporalRouted ? "Temporal routed" : "Runtime unknown"}</small>
        </div>
      </div>
    </aside>
  );
}
