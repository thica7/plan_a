import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface Bounds { x: number; y: number; width: number; height: number }
export interface DesktopWindowState {
  id: string; href: string; bounds: Bounds; minimized: boolean; maximized: boolean;
  zOrder?: number; navigationVersion?: number;
}

export function resourceKey(href: string) {
  const url = new URL(href, 'https://desktop.local');
  return /^\/runs\/[^/]+\/?$/.test(url.pathname) ? url.pathname.replace(/\/$/, '') : url.pathname + url.search;
}
function topWindow(windows: DesktopWindowState[]) {
  return windows.filter(w => !w.minimized).sort((a, b) => (b.zOrder ?? 0) - (a.zOrder ?? 0))[0]?.id ?? null;
}
function nextOrder(windows: DesktopWindowState[]) { return Math.max(0, ...windows.map(w => w.zOrder ?? 0)) + 1; }
interface DesktopState {
  windows: DesktopWindowState[]; activeId: string | null;
  open: (href: string) => string;
  focus: (id: string) => void;
  close: (id: string) => void;
  minimize: (id: string) => void;
  maximize: (id: string) => void;
  move: (id: string, bounds: Partial<Bounds>) => void;
  route: (id: string, href: string) => void;
}

export const useDesktopStore = create<DesktopState>()(persist((set, get) => ({
  windows: [], activeId: null,
  open(href) {
    const existing = get().windows.find(w => resourceKey(w.href) === resourceKey(href));
    if (existing) {
      set(s => ({ activeId: existing.id, windows: s.windows.map(w => w.id === existing.id ? { ...w, href, minimized: false, zOrder: nextOrder(s.windows), navigationVersion: (w.navigationVersion ?? 0) + 1 } : w) }));
      return existing.id;
    }
    const id = crypto.randomUUID();
    const offset = get().windows.length % 5 * 24;
    const width = typeof window === 'undefined' ? 1000 : Math.min(1080, window.innerWidth - 150);
    const height = typeof window === 'undefined' ? 680 : Math.min(740, window.innerHeight - 150);
    set(s => ({ activeId: id, windows: [...s.windows, { id, href, zOrder: nextOrder(s.windows), bounds: { x: 124 + offset, y: 66 + offset, width: Math.max(320, width), height: Math.max(280, height) }, minimized: false, maximized: false }] }));
    return id;
  },
  focus(id) { set(s => ({ activeId: id, windows: s.windows.map(w => w.id === id ? { ...w, minimized: false, zOrder: nextOrder(s.windows) } : w) })); },
  close(id) { set(s => { const windows = s.windows.filter(w => w.id !== id); return { windows, activeId: s.activeId === id ? topWindow(windows) : s.activeId }; }); },
  minimize(id) { set(s => ({ windows: s.windows.map(w => w.id === id ? { ...w, minimized: true } : w), activeId: s.activeId === id ? topWindow(s.windows.filter(w => w.id !== id)) : s.activeId })); },
  maximize(id) { set(s => ({ windows: s.windows.map(w => w.id === id ? { ...w, maximized: !w.maximized } : w) })); },
  move(id, bounds) { set(s => ({ windows: s.windows.map(w => w.id === id ? { ...w, bounds: { ...w.bounds, ...bounds } } : w) })); },
  route(id, href) {
    set(s => {
      if (!s.windows.some(w => w.id === id)) return s;
      const target = s.windows.find(w => w.id !== id && resourceKey(w.href) === resourceKey(href));
      if (!target) return { windows: s.windows.map(w => w.id === id ? { ...w, href } : w) };
      return {
        activeId: target.id,
        windows: s.windows.map(w => w.id === target.id
          ? { ...w, href, minimized: false, zOrder: nextOrder(s.windows), navigationVersion: (w.navigationVersion ?? 0) + 1 }
          // Restore programmatic navigation in the source router without replacing its resource.
          : w.id === id ? { ...w, navigationVersion: (w.navigationVersion ?? 0) + 1 } : w),
      };
    });
  },
}), {
  name: 'competiscope.desktop.v1',
  partialize: s => ({ windows: s.windows, activeId: s.activeId }),
  merge(persisted, current) {
    const saved = persisted as Pick<DesktopState, 'windows' | 'activeId'> | undefined;
    if (!saved?.windows) return current;
    const selected = new Map<string, DesktopWindowState>();
    saved.windows.forEach((w, index) => {
      const key = resourceKey(w.href), previous = selected.get(key);
      if (previous?.id === saved.activeId) return;
      if (!previous || w.id === saved.activeId || (w.zOrder ?? index) >= (previous.zOrder ?? 0)) selected.set(key, { ...w, zOrder: w.zOrder ?? index });
    });
    const windows = saved.windows.filter(w => selected.get(resourceKey(w.href))?.id === w.id).map(w => selected.get(resourceKey(w.href))!);
    return { ...current, windows, activeId: windows.some(w => w.id === saved.activeId) ? saved.activeId : topWindow(windows) };
  },
}));
