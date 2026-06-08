import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";

export function PageHeader({
  actions,
  eyebrow,
  meta,
  title,
}: {
  actions?: ReactNode;
  eyebrow?: string;
  meta?: ReactNode;
  title: string;
}) {
  return (
    <header className="page-header page-header-split">
      <div>
        {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
        <h1>{title}</h1>
        {meta ? <p>{meta}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}

export function Panel({
  actions,
  children,
  className = "",
  icon,
  title,
}: {
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  icon?: ReactNode;
  title?: string;
}) {
  return (
    <section className={`panel ${className}`.trim()}>
      {title || actions || icon ? (
        <div className="panel-heading-row">
          <h2>
            {icon}
            {title}
          </h2>
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function MetricCard({
  label,
  tone = "neutral",
  value,
}: {
  label: string;
  tone?: "good" | "neutral" | "warn";
  value: string | number;
}) {
  return (
    <span className={`metric-card ${tone}`}>
      <i aria-hidden />
      <strong>{value}</strong>
      <em>{label}</em>
    </span>
  );
}

export function StatusPill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "good" | "neutral" | "warn" | "bad";
}) {
  return <span className={`status-pill ${tone}`}>{children}</span>;
}

export function EmptyState({
  children,
  title,
}: {
  children?: ReactNode;
  title: string;
}) {
  return (
    <div className="empty-state compact">
      <AlertTriangle size={18} aria-hidden />
      <p>
        <strong>{title}</strong>
        {children ? <span>{children}</span> : null}
      </p>
    </div>
  );
}

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="empty-state compact">
      <Loader2 className="spin" size={18} aria-hidden />
      <p>{label}</p>
    </div>
  );
}

export function PassFailIcon({ ok }: { ok: boolean }) {
  return ok ? <CheckCircle2 size={15} aria-hidden /> : <AlertTriangle size={15} aria-hidden />;
}
