import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { NewRun } from "./pages/NewRun";
import { RunDetail } from "./pages/RunDetail";
import { HistoryPage } from "./pages/History";
import { EnterpriseWorkbench } from "./pages/EnterpriseWorkbench";
import KnowledgePage from "./pages/KnowledgePage";
import SearchPage from "./pages/SearchPage";
import CrawlPage from "./pages/CrawlPage";

export function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<NewRun />} />
        <Route path="/runs/:runId" element={<RunDetail />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/crawl" element={<CrawlPage />} />
        <Route path="/enterprise" element={<EnterpriseWorkbench initialView="overview" />} />
        <Route path="/competitors" element={<EnterpriseWorkbench initialView="competitors" />} />
        <Route path="/evidence" element={<EnterpriseWorkbench initialView="evidence" />} />
        <Route path="/reports" element={<EnterpriseWorkbench initialView="reports" />} />
        <Route path="/governance" element={<EnterpriseWorkbench initialView="governance" />} />
        <Route path="/activity" element={<EnterpriseWorkbench initialView="activity" />} />
      </Routes>
    </AppShell>
  );
}

