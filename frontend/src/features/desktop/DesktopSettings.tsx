import { useTheme } from '../../stores/theme';
import { useI18n } from '../../stores/i18n';
import { useRuntimeStatus } from '../../components/app-shell/useRuntimeStatus';
import { Link } from 'react-router-dom';

export function DesktopSettings() {
  const { theme, toggleTheme } = useTheme();
  const { locale, toggleLocale } = useI18n();
  const { runtime } = useRuntimeStatus();
  return <section className="desktop-settings"><p className="pixel-eyebrow">CONTROL PANEL</p><h1>系统设置</h1><p>调整工作环境，查看服务能力。</p>
    <div className="settings-row"><span>界面主题</span><button type="button" data-action-id="desktop.theme.toggle" data-action-audit="local" onClick={toggleTheme}>{theme === 'light' ? '切换深色' : '切换浅色'}</button></div>
    <div className="settings-row"><span>业务界面语言</span><button type="button" data-action-id="desktop.locale.toggle" data-action-audit="local" onClick={toggleLocale}>{locale === 'zh-CN' ? 'English' : '中文'}</button></div>
    <div className="settings-row"><span>后端连接</span><strong>{runtime ? '已连接' : '暂不可用'}</strong></div>
    <div className="settings-row"><span>搜索能力</span><strong>{runtime?.has_web_search_key ? '已配置' : '未配置'}</strong></div>
    <div className="settings-row"><span>工作流</span><strong>{runtime?.temporal_cutover_ready ? 'Temporal 已就绪' : '查看运行配置'}</strong></div>
    <Link to="/governance">打开治理与运行配置 →</Link>
  </section>;
}
