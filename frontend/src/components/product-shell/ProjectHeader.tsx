import { Star } from "lucide-react";
import type { ReactNode } from "react";

import { StatusPill } from "../ui";

export function ProjectHeader({
  actions,
  meta,
  status = "Active",
  title,
}: {
  actions?: ReactNode;
  meta: ReactNode;
  status?: string;
  title: string;
}) {
  return (
    <header className="product-project-header">
      <div className="project-title-block">
        <div className="project-title-row">
          <h1>{title}</h1>
          <Star size={18} aria-hidden />
          <StatusPill tone="good">{status}</StatusPill>
        </div>
        <p>{meta}</p>
      </div>
      {actions ? <div className="product-header-actions">{actions}</div> : null}
    </header>
  );
}
