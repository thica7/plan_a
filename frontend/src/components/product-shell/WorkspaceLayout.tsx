import type { ReactNode } from "react";

export function WorkspaceLayout({
  children,
  className = "",
  error,
  header,
  inspector,
  projectRail,
  statusStrip,
}: {
  children: ReactNode;
  className?: string;
  error?: ReactNode;
  header: ReactNode;
  inspector: ReactNode;
  projectRail: ReactNode;
  statusStrip: ReactNode;
}) {
  return (
    <section className={`work-surface product-workspace ${className}`.trim()}>
      {header}
      {error}
      {statusStrip}
      <div className="product-workspace-body">
        <div className="product-project-rail">{projectRail}</div>
        <main className="product-work-area">{children}</main>
        <aside className="product-inspector-rail">{inspector}</aside>
      </div>
    </section>
  );
}
