import { Link, NavLink } from "react-router-dom";
import { ChevronLeft, MoreVertical, Radar } from "lucide-react";
import { navGroups } from "./nav";
import { useTranslation } from "../../stores/i18n";

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
  const { t } = useTranslation();
  return (
    <aside aria-label={t('sidebar.nav')} className={isOpen ? "sidebar open" : "sidebar"}>
      <div className="sidebar-head">
        <Link className="brand" to="/" aria-label={t('sidebar.home')} onClick={onClose}>
          <span className="brand-mark">
            <Radar size={18} aria-hidden />
          </span>
          <span>
            <strong>{t('sidebar.brand')}</strong>
            <small>{t('sidebar.brandSub')}</small>
          </span>
        </Link>
      </div>

      <nav className="nav-list" aria-label={t('sidebar.primary')}>
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
          <strong>{systemReady ? t('sidebar.ready') : t('sidebar.attention')}</strong>
          <small>{temporalRouted ? t('sidebar.temporalRouted') : t('sidebar.runtimeUnknown')}</small>
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

      <button className="sidebar-collapse" onClick={onClose} type="button" aria-label={t('sidebar.collapse')}>
        <ChevronLeft size={15} aria-hidden />
        {t('sidebar.collapseLabel')}
      </button>
    </aside>
  );
}
