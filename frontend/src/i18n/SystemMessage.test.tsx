import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it } from 'vitest';
import { useI18n } from '../stores/i18n';
import { SystemMessage } from './SystemMessage';

beforeEach(() => useI18n.getState().setLocale('zh-CN'));

it('shows an unknown diagnostic through a Chinese disclosure while retaining the full original', async () => {
  const user = userEvent.setup();
  const original = 'Unexpected provider failure: Original Product / request:123';
  render(<p><SystemMessage message={original} /></p>);
  const disclosure = screen.getByRole('button', { name: '系统提示（查看原文）' });
  expect(disclosure).toHaveAttribute('aria-expanded', 'false');
  expect(screen.queryByText(original)).not.toBeInTheDocument();
  expect(screen.getByTitle(`系统原文：${original}`)).toBeInTheDocument();
  await user.click(disclosure);
  expect(screen.getByText(original)).toBeVisible();
  expect(screen.getByRole('button', { name: '收起原文' })).toHaveAttribute('aria-expanded', 'true');

  act(() => useI18n.getState().setLocale('en-US'));
  expect(screen.getByText(original)).toBeVisible();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

it('keeps diagnostics containing Chinese visible without classifying them as untranslated English', () => {
  render(<SystemMessage message='HTTP 502：服务暂不可用' />);
  expect(screen.getByText('HTTP 502：服务暂不可用')).toBeVisible();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});
