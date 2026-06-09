import {
  Activity,
  AlertTriangle,
  Bell,
  Building2,
  CheckCircle2,
  ChevronDown,
  Cuboid,
  HelpCircle,
  Menu,
} from "lucide-react";
import { ActionButton } from "../interaction/ActionButton";
import { ActionLink } from "../interaction/ActionLink";
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
  return (
    <header className="topbar">
      <div className="topbar-context">
        <ActionButton
          className="topbar-menu-button"
          aria-label="Open navigation"
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
          disabledReason="Workspace switching is not included in this demo build."
        >
          <Building2 size={17} aria-hidden />
          <span>
            <strong>Acme Corp</strong>
            <small>Workspace</small>
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
          disabledReason="Product switching is not included in this demo build."
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
          AI Research
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
          aria-label="Notifications"
          authenticity={{
            actionId: 'topbar.notifications.open',
            kind: 'disabled',
            description: 'notifications panel not available in demo'
          }}
          disabled
          disabledReason="Notifications panel is not included in this demo build."
        >
          <Bell size={17} aria-hidden />
          <i aria-hidden />
        </ActionButton>

        <ActionButton
          className="topbar-icon-button"
          aria-label="Help"
          authenticity={{
            actionId: 'topbar.help.open',
            kind: 'disabled',
            description: 'help panel not available in demo'
          }}
          disabled
          disabledReason="Help panel is not included in this demo build."
        >
          <HelpCircle size={17} aria-hidden />
        </ActionButton>

        <div className="topbar-user">
          <span className="avatar">AC</span>
          <strong>Acme Admin</strong>
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
