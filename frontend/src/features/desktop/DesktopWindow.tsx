import { useRef, type ReactNode, type PointerEvent, type KeyboardEvent } from 'react';
import { appForHref } from './apps';
import { PixelIcon } from './PixelIcon';
import { useDesktopStore, type DesktopWindowState } from './windowStore';
import { useTranslation } from '../../stores/i18n';

export function DesktopWindow({ state, index, children }: { state: DesktopWindowState; index: number; children: ReactNode }) {
  const { focus, minimize, maximize, close, move, activeId } = useDesktopStore();
  const gesture = useRef<{ x: number; y: number; start: DesktopWindowState['bounds']; resize: boolean } | null>(null);
  const { locale, t } = useTranslation();
  const app = appForHref(state.href, locale);
  function start(event: PointerEvent, resize = false) {
    if (window.innerWidth <= 760 || state.maximized || event.button !== 0 || (!resize && (event.target as HTMLElement).closest('.window-controls'))) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current = { x: event.clientX, y: event.clientY, start: state.bounds, resize };
  }
  function drag(event: PointerEvent) {
    const g = gesture.current;
    if (!g) return;
    const dx = event.clientX - g.x, dy = event.clientY - g.y;
    if (g.resize) move(state.id, { width: Math.max(320, Math.min(window.innerWidth - state.bounds.x - 8, g.start.width + dx)), height: Math.max(250, Math.min(window.innerHeight - state.bounds.y - 64, g.start.height + dy)) });
    else move(state.id, { x: Math.max(0, Math.min(window.innerWidth - 180, g.start.x + dx)), y: Math.max(0, Math.min(window.innerHeight - 110, g.start.y + dy)) });
  }
  function moveByKey(event: KeyboardEvent) {
    const delta = ({ ArrowLeft: [-16, 0], ArrowRight: [16, 0], ArrowUp: [0, -16], ArrowDown: [0, 16] } as Record<string, number[]>)[event.key];
    if (delta && !state.maximized && window.innerWidth > 760) { event.preventDefault(); move(state.id, { x: Math.max(0, Math.min(window.innerWidth - 180, state.bounds.x + delta[0])), y: Math.max(0, Math.min(window.innerHeight - 110, state.bounds.y + delta[1])) }); }
  }
  return <section aria-label={app.title} className={`desktop-window ${activeId === state.id ? 'focused' : ''} ${state.maximized ? 'maximized' : ''}`} hidden={state.minimized}
    onPointerDownCapture={() => { if (activeId !== state.id) focus(state.id); }}
    style={{ left: state.bounds.x, top: state.bounds.y, width: state.bounds.width, height: state.bounds.height, zIndex: index + 10 }}>
    <header className="pixel-titlebar" onPointerDown={e => start(e)} onPointerMove={drag} onPointerUp={() => { gesture.current = null; }} onPointerCancel={() => { gesture.current = null; }} onDoubleClick={e => { if (window.innerWidth > 760 && !(e.target as HTMLElement).closest('button')) maximize(state.id); }}>
      <button type="button" data-action-id="desktop.window.focus" data-action-audit="local" className="window-title" aria-label={window.innerWidth > 760 ? t('desktop.moveWindow').replace('{title}', app.title) : app.title} onKeyDown={moveByKey} onClick={() => focus(state.id)}><PixelIcon name={app.icon} /><span>{app.title}</span></button>
      <div className="window-controls"><button type="button" data-action-id="desktop.window.minimize" data-action-audit="local" aria-label={`${t('desktop.minimize')} ${app.title}`} onClick={() => minimize(state.id)}>—</button><button type="button" data-action-id="desktop.window.maximize" data-action-audit="local" className="window-maximize" aria-label={`${state.maximized ? t('desktop.restore') : t('desktop.maximize')} ${app.title}`} onClick={() => maximize(state.id)}>□</button><button type="button" data-action-id="desktop.window.close" data-action-audit="local" aria-label={`${t('common.close')} ${app.title}`} onClick={() => close(state.id)}>×</button></div>
    </header>
    <div className="window-content">{children}</div>
    <button type="button" data-action-id="desktop.window.resize" data-action-audit="local" className="resize-grip" aria-label={`${t('desktop.resize')} ${app.title}`} onPointerDown={e => start(e, true)} onPointerMove={drag} onPointerUp={() => { gesture.current = null; }} onPointerCancel={() => { gesture.current = null; }} onKeyDown={e => { if (e.key.startsWith('Arrow')) { e.preventDefault(); move(state.id, { width: Math.max(320, state.bounds.width + (e.key === 'ArrowLeft' ? -16 : e.key === 'ArrowRight' ? 16 : 0)), height: Math.max(250, state.bounds.height + (e.key === 'ArrowUp' ? -16 : e.key === 'ArrowDown' ? 16 : 0)) }); } }}>◢</button>
  </section>;
}
