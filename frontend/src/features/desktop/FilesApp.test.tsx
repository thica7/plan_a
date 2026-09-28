import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { FilesApp } from './FilesApp';
import { getArtifactPreview } from '../../api/client';

vi.mock('../../api/client', () => ({
  listEnterpriseProjects: vi.fn().mockResolvedValue([{ id: 'p1', name: 'AI 竞品研究' }]),
  listProjectEvidence: vi.fn().mockResolvedValue([{ id: 'e1', title: '官方定价页', snippet: 'Pro 套餐每月 29 美元', source_type: 'official', quality_label: 'accepted', url: 'https://example.com/pricing', captured_at: '2026-09-28' }]),
  listProjectReportVersions: vi.fn().mockResolvedValue([{ id: 'r1', report_md: '# 定价报告', version_number: 1, status: 'draft' }]),
  listArtifacts: vi.fn().mockResolvedValue([{ id: 'a1', filename: 'pricing.pdf', artifact_type: 'pdf', byte_size: 512, created_at: '2026-09-28' }]),
  getArtifactPreview: vi.fn().mockResolvedValue({ preview_type: 'text', content_text: '原始文件内容', preview_available: true }),
}));

it('opens evidence, report and artifact from a project file explorer', async () => {
  const user = userEvent.setup();
  render(<MemoryRouter><FilesApp /></MemoryRouter>);
  await user.click(await screen.findByRole('button', { name: /官方定价页/ }));
  expect(screen.getByText('Pro 套餐每月 29 美元')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /报告/ }));
  await user.click(await screen.findByRole('button', { name: /版本 1/ }));
  expect(screen.getByText('# 定价报告')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /附件/ }));
  await user.click(await screen.findByRole('button', { name: /pricing.pdf/ }));
  expect(await screen.findByText('原始文件内容')).toBeInTheDocument();
});

it('stops showing a loading preview when an attachment fails to load', async () => {
  vi.mocked(getArtifactPreview).mockRejectedValueOnce(new Error('文件读取失败'));
  const user = userEvent.setup();
  render(<MemoryRouter><FilesApp /></MemoryRouter>);
  await user.click(screen.getByRole('button', { name: /附件/ }));
  await user.click(await screen.findByRole('button', { name: /pricing.pdf/ }));
  expect(await screen.findByRole('alert')).toHaveTextContent('文件读取失败');
  expect(screen.queryByText('正在读取预览…')).not.toBeInTheDocument();
});
