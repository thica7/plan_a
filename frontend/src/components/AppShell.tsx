import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { routeTitle } from "./app-shell/nav";
import { Sidebar } from "./app-shell/Sidebar";
import { Topbar } from "./app-shell/Topbar";
import { useRuntimeStatus } from "./app-shell/useRuntimeStatus";

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { runtime, systemReady, temporalRouted } = useRuntimeStatus();
  const routeLabel = useMemo(() => routeTitle(location.pathname), [location.pathname]);

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  return (
    <div className={sidebarOpen ? "app-shell sidebar-open" : "app-shell"}>
      <Sidebar
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        systemReady={systemReady}
        temporalRouted={temporalRouted}
      />
      <button
        aria-label="Close navigation"
        className="shell-backdrop"
        onClick={() => setSidebarOpen(false)}
        type="button"
      />
      <div className="content-shell">
        <Topbar
          onMenuClick={() => setSidebarOpen((value) => !value)}
          routeLabel={routeLabel}
          runtime={runtime}
        />
        <main className="main-pane">{children}</main>
      </div>
    </div>
  );
}
