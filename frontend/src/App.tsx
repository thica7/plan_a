import { NavLink, Route, Routes } from "react-router-dom";
import { Activity, BookOpen, History, Radar, Search, Workflow } from "lucide-react";
import { NewRun } from "./pages/NewRun";
import { RunDetail } from "./pages/RunDetail";
import { HistoryPage } from "./pages/History";
import KnowledgePage from "./pages/KnowledgePage";
import SearchPage from "./pages/SearchPage";
import CrawlPage from "./pages/CrawlPage";

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
          <NavLink to="/knowledge">
            <BookOpen size={18} aria-hidden />
            Knowledge
          </NavLink>
          <NavLink to="/search">
            <Search size={18} aria-hidden />
            Search
          </NavLink>
          <NavLink to="/crawl">
            <Workflow size={18} aria-hidden />
            Crawl
          </NavLink>
        </nav>
      </aside>

      <main className="main-pane">
        <Routes>
          <Route path="/" element={<NewRun />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/crawl" element={<CrawlPage />} />
        </Routes>
      </main>
    </div>
  );
}

