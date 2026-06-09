import { Link, NavLink } from "react-router-dom";
import { ChevronLeft, MoreVertical, Radar } from "lucide-react";
import { navGroups } from "./nav";

export function Sidebar({
  isOpen,
  onClose,
  systemReady,
  temporalRouted,
}: {
  isOpen: boolean;
  onClose: () => void;
  systemReady: boolean;
  temporalRouted: boolean;
}) {
  return (
    <aside aria-label="Product navigation" className={isOpen ? "sidebar open" : "sidebar"}>
      <div className="sidebar-head">
        <Link className="brand" to="/" aria-label="Competiscope home" onClick={onClose}>
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
                  <NavLink end={item.end} key={item.to} onClick={onClose} to={item.to}>
                    <Icon size={17} aria-hidden />
                    <span>{item.label}</span>
                  </NavLink>
                );
              })}
            </div>
          </section>
        ))}
      </nav>

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

      <button className="sidebar-collapse" onClick={onClose} type="button" aria-label="Collapse sidebar">
        <ChevronLeft size={15} aria-hidden />
        Collapse
      </button>
    </aside>
  );
}
