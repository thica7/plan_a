import { Star } from "lucide-react";
import type { ReactNode } from "react";

import { StatusPill } from "../ui";
import { useTranslation } from '../../stores/i18n';
import { displayLabel } from '../../i18n/display';

export function ProjectHeader({
  actions,
  meta,
  status = "active",
  title,
}: {
  actions?: ReactNode;
  meta: ReactNode;
  status?: string;
  title: string;
}) {
  const { locale } = useTranslation();
  return (
    <header className="product-project-header">
      <div className="project-title-block">
        <div className="project-title-row">
          <h1>{title}</h1>
          <Star size={18} aria-hidden />
          <StatusPill tone="good">{displayLabel(status, locale)}</StatusPill>
        </div>
        <p>{meta}</p>
      </div>
      {actions ? <div className="product-header-actions">{actions}</div> : null}
    </header>
  );
}
