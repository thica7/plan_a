import { useEffect, useState } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { appForHref, BusinessRoutes, desktopApps } from './apps';
import { PixelIcon } from './PixelIcon';
import { DesktopWindow } from './DesktopWindow';
import { useDesktopStore } from './windowStore';
import { useRuntimeStatus } from '../../components/app-shell/useRuntimeStatus';

function RouteSync({ id }: { id: string }) {
  const location = useLocation();
  useEffect(() => {
    const href = location.pathname + location.search + location.hash;
    const state = useDesktopStore.getState();
    if (state.windows.find(w => w.id === id)?.href !== href) state.route(id, href);
    if (state.activeId === id) window.history.replaceState(null, '', href);
  }, [id, location.pathname, location.search, location.hash]);
  return null;
}

export function Desktop() {
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
  return <main className="pixel-desktop">
    <header className="desktop-menubar"><div className="desktop-brand"><PixelIcon name="research" /><strong>COMPETISCOPE</strong><span>Research OS</span></div><span className="desktop-connection"><i className={runtime ? 'connected' : ''} />{runtime ? '服务已连接' : '服务暂不可用'}</span></header>
    <nav className="desktop-icons" aria-label="桌面应用">{desktopApps.map(app => <button type="button" data-action-id="desktop.app.launch" data-action-audit="local" key={app.href} className="desktop-shortcut" onClick={() => launch(app.href)}><PixelIcon name={app.icon} /><span>{app.title}</span></button>)}</nav>
    <div className="desktop-wallpaper" aria-hidden="true"><span>YOUR NEXT</span><strong>GOOD QUESTION.</strong><p>研究 / 证据 / 判断</p><div className="pixel-mountain" /></div>
    {ready && windows.map((w, index) => <DesktopWindow key={w.id} state={w} index={index}><MemoryRouter initialEntries={[w.href]}><RouteSync id={w.id} /><BusinessRoutes /></MemoryRouter></DesktopWindow>)}
    {menu && <nav className="desktop-launcher" aria-label="应用菜单"><p className="launcher-heading">应用程序</p>{desktopApps.map(app => <button type="button" data-action-id="desktop.menu.launch" data-action-audit="local" key={app.href} onClick={() => launch(app.href)}><PixelIcon name={app.icon} /><span><strong>{app.title}</strong><small>{app.subtitle}</small></span></button>)}</nav>}
    <footer className="desktop-taskbar"><button type="button" data-action-id="desktop.start.toggle" data-action-audit="local" className="start-button" aria-expanded={menu} onClick={() => setMenu(v => !v)}><PixelIcon name="grid" />开始</button><div className="taskbar-apps">{windows.map(w => <button type="button" data-action-id="desktop.taskbar.restore" data-action-audit="local" key={w.id} className={activeId === w.id && !w.minimized ? 'active' : ''} onClick={() => focus(w.id)} aria-label={`恢复 ${appForHref(w.href).title}`}><PixelIcon name={appForHref(w.href).icon} /><span>{appForHref(w.href).title}</span></button>)}</div><time>{now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</time></footer>
  </main>;
}
