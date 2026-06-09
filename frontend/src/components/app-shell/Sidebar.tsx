import { Link, NavLink } from "react-router-dom";
import { ChevronLeft, MoreVertical, Radar, Settings, Users } from "lucide-react";
import { navGroups } from "./nav";

export function Sidebar({
  systemReady,
  temporalRouted,
}: {
  systemReady: boolean;
  temporalRouted: boolean;
}) {
  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <Link className="brand" to="/" aria-label="Competiscope home">
          <span className="brand-mark">
            <Radar size={18} aria-hidden />
          </span>
          <span>
            <strong>Competiscope</strong>
            <small>AI Competitive Intel</small>
          </span>
        </Link>
      </div>

      <nav className="nav-list" aria-label="Primary">
        {navGroups.map((group) => (
          <section className="nav-section" key={group.label}>
            <strong>{group.label}</strong>
            <div>
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink end={item.end} key={item.to} to={item.to}>
                    <Icon size={17} aria-hidden />
                    <span>{item.label}</span>
                  </NavLink>
                );
              })}
            </div>
          </section>
        ))}
      </nav>

      <div className="sidebar-admin">
        <strong>Admin</strong>
        <NavLink to="/governance">
          <Settings size={17} aria-hidden />
          <span>Settings</span>
        </NavLink>
        <NavLink to="/activity">
          <Users size={17} aria-hidden />
          <span>Members</span>
        </NavLink>
      </div>

      <div className="sidebar-system">
        <span className={systemReady ? "system-dot ready" : "system-dot warn"} />
        <div>
          <strong>{systemReady ? "Ready for real runs" : "Needs attention"}</strong>
          <small>{temporalRouted ? "Temporal routed" : "Runtime unknown"}</small>
        </div>
      </div>

      <div className="sidebar-profile">
        <span className="avatar">AC</span>
        <div>
          <strong>Acme Admin</strong>
          <small>admin@workspace</small>
        </div>
        <MoreVertical size={15} aria-hidden />
      </div>

      <button className="sidebar-collapse" type="button" aria-label="Collapse sidebar">
        <ChevronLeft size={15} aria-hidden />
        Collapse
      </button>
    </aside>
  );
}
