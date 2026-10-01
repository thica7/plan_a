import { useEffect, useRef, useState } from 'react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { appForHref, BusinessRoutes, localizedDesktopApps } from './apps';
import { PixelIcon } from './PixelIcon';
import { DesktopWindow } from './DesktopWindow';
import { useDesktopStore } from './windowStore';
import { useRuntimeStatus } from '../../components/app-shell/useRuntimeStatus';
import { useTranslation } from '../../stores/i18n';
import { PastoralWallpaper } from './PastoralWallpaper';

function RouteSync({ id }: { id: string }) {
  const location = useLocation();
  const navigate = useNavigate();
  const current = useDesktopStore(s => s.windows.find(w => w.id === id));
  const appliedNavigation = useRef(current?.navigationVersion);
  useEffect(() => {
    if (!current) return;
    const href = location.pathname + location.search + location.hash;
    if (appliedNavigation.current !== current.navigationVersion) {
      appliedNavigation.current = current.navigationVersion;
      if (href !== current.href) { navigate(current.href, { replace: true }); return; }
    }
    const state = useDesktopStore.getState();
    if (state.windows.find(w => w.id === id)?.href !== href) state.route(id, href);
    if (useDesktopStore.getState().activeId === id) window.history.replaceState(null, '', href);
  }, [id, location.pathname, location.search, location.hash, current?.navigationVersion, navigate]);
  return null;
}

export function Desktop() {
  const { locale, t } = useTranslation();
  const desktopApps = localizedDesktopApps(locale);
  const { windows, activeId, open, focus } = useDesktopStore();
  const [initialHref] = useState(() => window.location.pathname + window.location.search + window.location.hash);
  const [ready, setReady] = useState(false);
  const [menu, setMenu] = useState(false);
  const [now, setNow] = useState(new Date());
  const { runtime } = useRuntimeStatus();
  useEffect(() => {
    const state = useDesktopStore.getState();
    if (!state.windows.length || initialHref !== '/') state.open(initialHref);
    setReady(true);
    const pop = () => state.open(window.location.pathname + window.location.search + window.location.hash);
    window.addEventListener('popstate', pop);
    const timer = window.setInterval(() => setNow(new Date()), 30000);
    return () => { window.removeEventListener('popstate', pop); window.clearInterval(timer); };
  }, [initialHref]);
  useEffect(() => {
    if (!ready) return;
    const current = windows.find(w => w.id === activeId);
    if (current) window.history.replaceState(null, '', current.href);
  }, [activeId, windows, ready]);
  useEffect(() => {
    const resize = () => { const state = useDesktopStore.getState(); for (const w of state.windows) state.move(w.id, { x: Math.min(w.bounds.x, Math.max(0, window.innerWidth - 180)), y: Math.min(w.bounds.y, Math.max(0, window.innerHeight - 110)) }); };
    resize(); window.addEventListener('resize', resize); return () => window.removeEventListener('resize', resize);
  }, []);
  function launch(href: string) { open(href); setMenu(false); }
  const stacking = [...windows].sort((a, b) => (a.zOrder ?? windows.indexOf(a)) - (b.zOrder ?? windows.indexOf(b))).map(w => w.id);
  return <main className="pixel-desktop">
    <PastoralWallpaper />
    <header className="desktop-menubar"><div className="desktop-brand"><PixelIcon name="research" /><strong>COMPETISCOPE</strong><span>{t('desktop.researchOS')}</span></div><span className="desktop-connection"><i className={runtime ? 'connected' : ''} />{runtime ? t('settings.connected') : t('settings.unavailable')}</span></header>
    <nav className="desktop-icons" aria-label={t('desktop.apps')}>{desktopApps.map(app => <button type="button" data-action-id="desktop.app.launch" data-action-audit="local" key={app.href} className="desktop-shortcut" onClick={() => launch(app.href)}><PixelIcon name={app.icon} /><span>{app.title}</span></button>)}</nav>
    {ready && windows.map(w => <DesktopWindow key={w.id} state={w} index={stacking.indexOf(w.id)}><MemoryRouter initialEntries={[w.href]}><RouteSync id={w.id} /><BusinessRoutes /></MemoryRouter></DesktopWindow>)}
    {menu && <nav className="desktop-launcher" aria-label={t('desktop.menu')}><p className="launcher-heading">{t('desktop.applications')}</p>{desktopApps.map(app => <button type="button" data-action-id="desktop.menu.launch" data-action-audit="local" key={app.href} onClick={() => launch(app.href)}><PixelIcon name={app.icon} /><span><strong>{app.title}</strong><small>{app.subtitle}</small></span></button>)}</nav>}
    <footer className="desktop-taskbar"><button type="button" data-action-id="desktop.start.toggle" data-action-audit="local" className="start-button" aria-expanded={menu} onClick={() => setMenu(v => !v)}><PixelIcon name="grid" />{t('desktop.start')}</button><div className="taskbar-apps">{windows.map(w => <button type="button" data-action-id="desktop.taskbar.restore" data-action-audit="local" key={w.id} className={activeId === w.id && !w.minimized ? 'active' : ''} onClick={() => focus(w.id)} aria-label={`${t('desktop.restore')} ${appForHref(w.href, locale).title}`}><PixelIcon name={appForHref(w.href, locale).icon} /><span>{appForHref(w.href, locale).title}</span></button>)}</div><time>{now.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}</time></footer>
  </main>;
}
