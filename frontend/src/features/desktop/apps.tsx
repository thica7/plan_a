import { Route, Routes } from 'react-router-dom';
import { NewRun } from '../../pages/NewRun';
import { RunDetail } from '../../pages/RunDetail';
import { HistoryPage } from '../../pages/History';
import { EnterpriseWorkbench } from '../../pages/EnterpriseWorkbench';
import KnowledgePage from '../../pages/KnowledgePage';
import SearchPage from '../../pages/SearchPage';
import CrawlPage from '../../pages/CrawlPage';
import { DesktopSettings } from './DesktopSettings';
import { FilesApp } from './FilesApp';
import { translate, type Locale } from '../../stores/i18n';

export const desktopApps = [
  { href: '/', title: '研究任务', icon: 'research', subtitle: '从问题开始研究' },
  { href: '/history', title: '任务管理器', icon: 'tasks', subtitle: '任务进度与历史' },
  { href: '/knowledge', title: '知识库', icon: 'book', subtitle: '可复用的知识文档' },
  { href: '/files', title: '证据文件', icon: 'folder', subtitle: '来源、文件与引用' },
  { href: '/competitors', title: '竞品档案', icon: 'grid', subtitle: '竞品与比较' },
  { href: '/reports', title: '报告阅读器', icon: 'report', subtitle: '阅读、审阅与导出' },
  { href: '/search', title: '检索工具', icon: 'search', subtitle: '查找知识证据' },
  { href: '/crawl', title: '采集队列', icon: 'download', subtitle: '采集与入库' },
  { href: '/activity', title: '活动中心', icon: 'bell', subtitle: '通知与运行活动' },
  { href: '/settings', title: '系统设置', icon: 'settings', subtitle: '主题、语言与状态' },
];
export function localizedDesktopApps(locale: Locale) {
  return desktopApps.map(app => ({ ...app, title: translate(`desktop.app.${app.icon}.title`, locale), subtitle: translate(`desktop.app.${app.icon}.subtitle`, locale) }));
}
export function appForHref(href: string, locale: Locale = 'zh-CN') {
  const path = new URL(href, 'https://desktop.local').pathname;
  const apps = localizedDesktopApps(locale);
  if (path.startsWith('/runs/')) return { ...apps[0], title: `${translate('desktop.analysis', locale)} · ${path.slice(6).slice(0, 16)}` };
  return apps.find(a => a.href === path) ?? { ...apps[0], title: translate('desktop.workbench', locale) };
}
export function BusinessRoutes() {
  return <Routes>
    <Route path="/" element={<NewRun />} /><Route path="/runs/:runId" element={<RunDetail />} />
    <Route path="/history" element={<HistoryPage />} /><Route path="/knowledge" element={<KnowledgePage />} />
    <Route path="/search" element={<SearchPage />} /><Route path="/crawl" element={<CrawlPage />} />
    <Route path="/settings" element={<DesktopSettings />} /><Route path="/files" element={<FilesApp />} />
    <Route path="/enterprise" element={<EnterpriseWorkbench initialView="overview" />} />
    <Route path="/competitors" element={<EnterpriseWorkbench initialView="competitors" />} />
    <Route path="/evidence" element={<EnterpriseWorkbench initialView="evidence" />} />
    <Route path="/reports" element={<EnterpriseWorkbench initialView="reports" />} />
    <Route path="/governance" element={<EnterpriseWorkbench initialView="governance" />} />
    <Route path="/activity" element={<EnterpriseWorkbench initialView="activity" />} />
    <Route path="*" element={<NewRun />} />
  </Routes>;
}
