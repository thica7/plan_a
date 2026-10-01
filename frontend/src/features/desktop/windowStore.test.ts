import { beforeEach, describe, expect, it } from 'vitest';
import { useDesktopStore } from './windowStore';

describe('desktop windows', () => {
  beforeEach(() => useDesktopStore.setState({ windows: [], activeId: null }));
  it('focuses without changing render order', () => {
    const first = useDesktopStore.getState().open('/knowledge');
    useDesktopStore.getState().open('/settings');
    const order = useDesktopStore.getState().windows.map(w => w.id);
    useDesktopStore.getState().focus(first);
    expect(useDesktopStore.getState().windows.map(w => w.id)).toEqual(order);
  });
  it('reuses a run across views and anchors but preserves other resource queries', () => {
    const first = useDesktopStore.getState().open('/runs/a?view=report');
    expect(useDesktopStore.getState().open('/runs/a?view=quality#issue')).toBe(first);
    expect(useDesktopStore.getState().windows[0].href).toBe('/runs/a?view=quality#issue');
    expect(useDesktopStore.getState().open('/runs/b')).not.toBe(first);
    expect(useDesktopStore.getState().open('/knowledge?document=a')).not.toBe(useDesktopStore.getState().open('/knowledge?document=b'));
  });
  it('routes an internal resource collision to the existing window and keeps its source', () => {
    const target = useDesktopStore.getState().open('/runs/a?view=report');
    const source = useDesktopStore.getState().open('/history');
    useDesktopStore.getState().minimize(target);
    const before = useDesktopStore.getState().windows;
    useDesktopStore.getState().route(source, '/runs/a?view=quality#issue');
    const state = useDesktopStore.getState();
    expect(state.windows.map(w => w.id)).toEqual(before.map(w => w.id));
    expect(state.windows.find(w => w.id === source)?.href).toBe('/history');
    expect(state.windows.find(w => w.id === target)).toMatchObject({ href: '/runs/a?view=quality#issue', minimized: false, bounds: before[0].bounds });
    expect(state.activeId).toBe(target);
    expect(state.windows.every(w => w.navigationVersion === 1)).toBe(true);
  });
  it('deduplicates legacy run windows keeping active bounds and other resources', async () => {
    const bounds = { x: 10, y: 20, width: 500, height: 400 };
    const make = (id: string, href: string) => ({ id, href, bounds, minimized: false, maximized: false });
    localStorage.setItem('competiscope.desktop.v1', JSON.stringify({ state: { activeId: 'active', windows: [make('active', '/runs/a?view=report'), make('later', '/runs/a#heading'), make('other', '/knowledge?document=a')] }, version: 0 }));
    await useDesktopStore.persist.rehydrate();
    expect(useDesktopStore.getState().windows.map(w => w.id)).toEqual(['active', 'other']);
    expect(useDesktopStore.getState().windows[0].bounds).toEqual(bounds);
    expect(useDesktopStore.getState().activeId).toBe('active');
  });
  it('restores an existing app instead of duplicating its window', () => {
    const id = useDesktopStore.getState().open('/knowledge');
    useDesktopStore.getState().minimize(id);
    expect(useDesktopStore.getState().open('/knowledge')).toBe(id);
    expect(useDesktopStore.getState().windows).toHaveLength(1);
    expect(useDesktopStore.getState().windows[0].minimized).toBe(false);
  });
  it('keeps separate resources and restores maximized bounds', () => {
    const a = useDesktopStore.getState().open('/runs/a');
    useDesktopStore.getState().open('/runs/b');
    const before = useDesktopStore.getState().windows.find(w => w.id === a)!.bounds;
    useDesktopStore.getState().maximize(a);
    useDesktopStore.getState().maximize(a);
    expect(useDesktopStore.getState().windows.find(w => w.id === a)!.bounds).toEqual(before);
    useDesktopStore.getState().close(a);
    expect(useDesktopStore.getState().windows.map(w => w.href)).toEqual(['/runs/b']);
  });
});
