import { useMemo, type ReactNode } from "react";
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
  const { runtime, systemReady, temporalRouted } = useRuntimeStatus();
  const routeLabel = useMemo(() => routeTitle(location.pathname), [location.pathname]);

  return (
    <div className="app-shell">
      <Sidebar systemReady={systemReady} temporalRouted={temporalRouted} />
      <div className="content-shell">
        <Topbar routeLabel={routeLabel} runtime={runtime} />
        <main className="main-pane">{children}</main>
      </div>
    </div>
  );
}
