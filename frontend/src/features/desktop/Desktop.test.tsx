import { act, render, screen, within } from '@testing-library/react';
import { useLocation } from 'react-router-dom';
import { useState } from 'react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { Desktop } from './Desktop';
import { useDesktopStore } from './windowStore';
import { useI18n } from '../../stores/i18n';

vi.mock('../../components/app-shell/useRuntimeStatus', () => ({ useRuntimeStatus: () => ({ runtime: null }) }));
vi.mock('./apps', async () => {
  const actual = await vi.importActual<typeof import('./apps')>('./apps');
  return { ...actual, BusinessRoutes: () => { const location = useLocation(); const [count, setCount] = useState(0); return <div><output>{location.pathname + location.search + location.hash}</output><button onClick={() => setCount(count + 1)}>计数 {count}</button></div>; } };
});
beforeEach(() => { useI18n.getState().setLocale('zh-CN'); useDesktopStore.setState({ windows: [], activeId: null }); history.replaceState(null, '', '/'); });

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

it('synchronizes external run navigation without remounting and keeps DOM order on focus', async () => {
  history.replaceState(null, '', '/runs/a?view=report');
  const { container } = render(<Desktop />);
  const first = container.querySelector('.desktop-window')!;
  await userEvent.click(within(first as HTMLElement).getByText('计数 0'));
  act(() => { useDesktopStore.getState().open('/settings'); });
  const order = [...container.querySelectorAll('.desktop-window')];
  act(() => { useDesktopStore.getState().open('/runs/a?view=quality#issue'); });
  expect([...container.querySelectorAll('.desktop-window')]).toEqual(order);
  expect(within(first as HTMLElement).getByText('/runs/a?view=quality#issue')).toBeInTheDocument();
  expect(within(first as HTMLElement).getByText('计数 1')).toBeInTheDocument();
  expect(window.location.search + window.location.hash).toBe('?view=quality#issue');
});

it('keeps repeated focus below the taskbar while preserving window order', () => {
  const { container } = render(<Desktop />);
  const first = useDesktopStore.getState().windows[0].id;
  act(() => { useDesktopStore.getState().open('/settings'); });
  const order = [...container.querySelectorAll('.desktop-window')];
  act(() => { for (let index = 0; index < 1100; index++) useDesktopStore.getState().focus(first); });
  expect([...container.querySelectorAll('.desktop-window')]).toEqual(order);
  expect(Number((order[0] as HTMLElement).style.zIndex)).toBeLessThan(1000);
  expect(Number((order[0] as HTMLElement).style.zIndex)).toBeGreaterThan(Number((order[1] as HTMLElement).style.zIndex));
});

it('updates desktop apps and window controls when the language changes', async () => {
  render(<Desktop />);
  await userEvent.click(screen.getByRole('button', { name: '知识库' }));
  act(() => useI18n.getState().setLocale('en-US'));
  expect(screen.getByRole('navigation', { name: 'Desktop apps' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Minimize Knowledge' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Restore Knowledge' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Start' })).toBeInTheDocument();
  act(() => useI18n.getState().setLocale('zh-CN'));
});
