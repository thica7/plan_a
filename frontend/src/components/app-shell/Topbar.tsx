import {
  Activity,
  AlertTriangle,
  Bell,
  Building2,
  CheckCircle2,
  ChevronDown,
  Cuboid,
  Globe,
  HelpCircle,
  Menu,
  Moon,
  Sun,
} from "lucide-react";
import { ActionButton } from "../interaction/ActionButton";
import { ActionLink } from "../interaction/ActionLink";
import { useI18n } from "../../stores/i18n";
import { useTheme } from "../../stores/theme";
import type { RuntimeConfig } from "../../api/types";

export function Topbar({
  onMenuClick,
  routeLabel,
  runtime,
}: {
  onMenuClick: () => void;
  routeLabel: string;
  runtime: RuntimeConfig | null;
}) {
  const { t, toggleLocale, locale } = useI18n();
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <header className="topbar">
      <div className="topbar-context">
        <ActionButton
          className="topbar-menu-button"
          aria-label={t('topbar.menu')}
          authenticity={{
            actionId: 'topbar.navigation.open',
            kind: 'local',
            description: 'opens mobile navigation menu'
          }}
          onClick={onMenuClick}
        >
          <Menu size={18} aria-hidden />
        </ActionButton>

        <ActionButton
          className="context-switcher workspace-context"
          authenticity={{
            actionId: 'topbar.workspace.switch',
            kind: 'disabled',
            description: 'workspace switcher not available in demo'
          }}
          disabled
          disabledReason={t('topbar.workspace.disabled')}
        >
          <Building2 size={17} aria-hidden />
          <span>
            <strong>{t('topbar.acmeCorp')}</strong>
            <small>{t('topbar.workspace')}</small>
          </span>
          <ChevronDown size={15} aria-hidden />
        </ActionButton>

        <ActionButton
          className="context-switcher product-context"
          authenticity={{
            actionId: 'topbar.product.switch',
            kind: 'disabled',
            description: 'product switcher not available in demo'
          }}
          disabled
          disabledReason={t('topbar.product.disabled')}
        >
          <Cuboid size={17} aria-hidden />
          <span>
            <strong>AI Competitive Intel</strong>
            <small>{routeLabel}</small>
          </span>
          <ChevronDown size={15} aria-hidden />
        </ActionButton>
      </div>

      <div className="topbar-actions" aria-label="System status">
        <ActionLink
          className="primary-link topbar-research-link"
          to="/"
          authenticity={{
            actionId: 'topbar.ai-research.open',
            kind: 'route',
            description: 'navigates to new research run page'
          }}
        >
          <Activity size={15} aria-hidden />
          {t('topbar.aiResearch')}
        </ActionLink>

        <StatusBadge
          good={Boolean(runtime?.temporal_cutover_ready)}
          label="Temporal"
        />
        <StatusBadge
          good={Boolean(runtime?.has_web_search_key)}
          label={runtime?.web_search_provider ?? "Search"}
        />
        <StatusBadge
          good={Boolean(runtime?.compliance_redaction_enabled)}
          label="Compliance"
        />

        <ActionButton
          className="topbar-icon-button"
          aria-label={isDark ? t('topbar.theme.light') : t('topbar.theme.dark')}
          authenticity={{
            actionId: 'topbar.theme.toggle',
            kind: 'local',
            description: 'toggles between light and dark theme'
          }}
          onClick={toggleTheme}
        >
          {isDark ? <Sun size={17} aria-hidden /> : <Moon size={17} aria-hidden />}
        </ActionButton>

        <ActionButton
          className="topbar-icon-button"
          aria-label={`Switch to ${locale === 'zh-CN' ? 'English' : '中文'}`}
          authenticity={{
            actionId: 'topbar.locale.toggle',
            kind: 'local',
            description: 'toggles between Chinese and English'
          }}
          onClick={toggleLocale}
        >
          <Globe size={17} aria-hidden />
          <span className="locale-badge">{locale === 'zh-CN' ? '中' : 'EN'}</span>
        </ActionButton>

        <ActionButton
          className="topbar-icon-button"
          aria-label={t('topbar.notifications')}
          authenticity={{
            actionId: 'topbar.notifications.open',
            kind: 'disabled',
            description: 'notifications panel not available in demo'
          }}
          disabled
          disabledReason={t('topbar.notifications.disabled')}
        >
          <Bell size={17} aria-hidden />
          <i aria-hidden />
        </ActionButton>

        <ActionButton
          className="topbar-icon-button"
          aria-label={t('topbar.help')}
          authenticity={{
            actionId: 'topbar.help.open',
            kind: 'disabled',
            description: 'help panel not available in demo'
          }}
          disabled
          disabledReason={t('topbar.help.disabled')}
        >
          <HelpCircle size={17} aria-hidden />
        </ActionButton>

        <div className="topbar-user">
          <span className="avatar">AC</span>
          <strong>{t('topbar.acmeAdmin')}</strong>
          <ChevronDown size={14} aria-hidden />
        </div>
      </div>
    </header>
  );
}

function StatusBadge({ good, label }: { good: boolean; label: string }) {
  return (
    <span className={good ? "status-badge good" : "status-badge warn"}>
      {good ? <CheckCircle2 size={14} aria-hidden /> : <AlertTriangle size={14} aria-hidden />}
      {label}
    </span>
  );
}
