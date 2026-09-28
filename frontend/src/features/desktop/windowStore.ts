import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface Bounds { x: number; y: number; width: number; height: number }
export interface DesktopWindowState {
  id: string; href: string; bounds: Bounds; minimized: boolean; maximized: boolean;
}
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
    const existing = get().windows.find(w => w.href === href);
    if (existing) { get().focus(existing.id); return existing.id; }
    const id = crypto.randomUUID();
    const offset = get().windows.length % 5 * 24;
    const width = typeof window === 'undefined' ? 1000 : Math.min(1080, window.innerWidth - 150);
    const height = typeof window === 'undefined' ? 680 : Math.min(740, window.innerHeight - 150);
    set(s => ({ activeId: id, windows: [...s.windows, { id, href, bounds: { x: 124 + offset, y: 66 + offset, width: Math.max(320, width), height: Math.max(280, height) }, minimized: false, maximized: false }] }));
    return id;
  },
  focus(id) { set(s => ({ activeId: id, windows: [...s.windows.filter(w => w.id !== id), ...s.windows.filter(w => w.id === id).map(w => ({ ...w, minimized: false }))] })); },
  close(id) { set(s => { const windows = s.windows.filter(w => w.id !== id); return { windows, activeId: s.activeId === id ? windows.filter(w => !w.minimized).slice(-1)[0]?.id ?? null : s.activeId }; }); },
  minimize(id) { set(s => ({ windows: s.windows.map(w => w.id === id ? { ...w, minimized: true } : w), activeId: s.activeId === id ? s.windows.filter(w => w.id !== id && !w.minimized).slice(-1)[0]?.id ?? null : s.activeId })); },
  maximize(id) { set(s => ({ windows: s.windows.map(w => w.id === id ? { ...w, maximized: !w.maximized } : w) })); },
  move(id, bounds) { set(s => ({ windows: s.windows.map(w => w.id === id ? { ...w, bounds: { ...w.bounds, ...bounds } } : w) })); },
  route(id, href) { set(s => ({ windows: s.windows.map(w => w.id === id ? { ...w, href } : w) })); },
}), { name: 'competiscope.desktop.v1', partialize: s => ({ windows: s.windows, activeId: s.activeId }) }));
