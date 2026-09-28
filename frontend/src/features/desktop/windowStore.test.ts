import { beforeEach, describe, expect, it } from 'vitest';
import { useDesktopStore } from './windowStore';

describe('desktop windows', () => {
  beforeEach(() => useDesktopStore.setState({ windows: [], activeId: null }));
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
