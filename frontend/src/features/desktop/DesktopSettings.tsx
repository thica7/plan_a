import { useTheme } from '../../stores/theme';
import { useI18n } from '../../stores/i18n';
import { useRuntimeStatus } from '../../components/app-shell/useRuntimeStatus';
import { Link } from 'react-router-dom';

export function DesktopSettings() {
  const { theme, toggleTheme } = useTheme();
  const { locale, toggleLocale, t } = useI18n();
  const { runtime } = useRuntimeStatus();
  return <section className="desktop-settings"><p className="pixel-eyebrow">{t('settings.eyebrow')}</p><h1>{t('settings.title')}</h1><p>{t('settings.description')}</p>
    <div className="settings-row"><span>{t('settings.theme')}</span><button type="button" data-action-id="desktop.theme.toggle" data-action-audit="local" onClick={toggleTheme}>{theme === 'light' ? t('settings.dark') : t('settings.light')}</button></div>
    <div className="settings-row"><span>{t('settings.language')}</span><button type="button" data-action-id="desktop.locale.toggle" data-action-audit="local" onClick={toggleLocale}>{locale === 'zh-CN' ? 'English' : '中文'}</button></div>
    <div className="settings-row"><span>{t('settings.backend')}</span><strong>{runtime ? t('settings.connected') : t('settings.unavailable')}</strong></div>
    <div className="settings-row"><span>{t('settings.search')}</span><strong>{runtime?.has_web_search_key ? t('settings.configured') : t('settings.notConfigured')}</strong></div>
    <div className="settings-row"><span>{t('settings.workflow')}</span><strong>{runtime?.temporal_cutover_ready ? t('settings.temporalReady') : t('settings.runtimeConfig')}</strong></div>
    <Link to="/governance">{t('settings.openGovernance')} →</Link>
  </section>;
}
