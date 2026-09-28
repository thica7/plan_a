import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { Desktop } from './Desktop';
import { useDesktopStore } from './windowStore';

vi.mock('../../components/app-shell/useRuntimeStatus', () => ({ useRuntimeStatus: () => ({ runtime: null }) }));
vi.mock('./apps', async () => {
  const actual = await vi.importActual<typeof import('./apps')>('./apps');
  return { ...actual, BusinessRoutes: () => <div>业务区域</div> };
});
beforeEach(() => { useDesktopStore.setState({ windows: [], activeId: null }); history.replaceState(null, '', '/'); });

it('opens, minimizes, restores and closes a real application window', async () => {
  const user = userEvent.setup();
  render(<Desktop />);
  await user.click(screen.getByRole('button', { name: '知识库' }));
  expect(useDesktopStore.getState().windows).toHaveLength(2);
  await user.click(screen.getByRole('button', { name: '最小化 知识库' }));
  expect(useDesktopStore.getState().windows.find(w => w.href === '/knowledge')?.minimized).toBe(true);
  await user.click(screen.getByRole('button', { name: '恢复 知识库' }));
  expect(screen.getByRole('button', { name: '关闭 知识库' })).toBeVisible();
  await user.click(screen.getByRole('button', { name: '关闭 知识库' }));
  expect(useDesktopStore.getState().windows).toHaveLength(1);
});

it('keeps an incoming run deep link when a different window was persisted', async () => {
  useDesktopStore.setState({
    windows: [{ id: 'saved-settings', href: '/settings', bounds: { x: 80, y: 60, width: 700, height: 500 }, minimized: false, maximized: false }],
    activeId: 'saved-settings',
  });
  history.replaceState(null, '', '/runs/incoming');
  render(<Desktop />);
  expect(useDesktopStore.getState().windows.map(w => w.href)).toContain('/runs/incoming');
  expect(window.location.pathname).toBe('/runs/incoming');
});
