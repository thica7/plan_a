import { NavLink, Route, Routes } from "react-router-dom";
import { Activity, Briefcase, Database, FileText, History, Layers, Radar } from "lucide-react";
import { NewRun } from "./pages/NewRun";
import { RunDetail } from "./pages/RunDetail";
import { HistoryPage } from "./pages/History";
import { EnterpriseWorkbench } from "./pages/EnterpriseWorkbench";

export function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Radar size={28} aria-hidden />
          <div>
            <strong>Competiscope</strong>
            <span>Plan A console</span>
          </div>
        </div>
        <nav className="nav-list" aria-label="Primary">
          <NavLink to="/" end>
            <Activity size={18} aria-hidden />
            New run
          </NavLink>
          <NavLink to="/history">
            <History size={18} aria-hidden />
            History
          </NavLink>
          <NavLink to="/enterprise">
            <Briefcase size={18} aria-hidden />
            Enterprise
          </NavLink>
          <NavLink to="/competitors">
            <Layers size={18} aria-hidden />
            Competitors
          </NavLink>
          <NavLink to="/evidence">
            <Database size={18} aria-hidden />
            Evidence
          </NavLink>
          <NavLink to="/reports">
            <FileText size={18} aria-hidden />
            Reports
          </NavLink>
        </nav>
      </aside>

      <main className="main-pane">
        <Routes>
          <Route path="/" element={<NewRun />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/enterprise" element={<EnterpriseWorkbench initialTab="competitors" />} />
          <Route path="/competitors" element={<EnterpriseWorkbench initialTab="competitors" />} />
          <Route path="/evidence" element={<EnterpriseWorkbench initialTab="evidence" />} />
          <Route path="/reports" element={<EnterpriseWorkbench initialTab="reports" />} />
        </Routes>
      </main>
    </div>
  );
}

