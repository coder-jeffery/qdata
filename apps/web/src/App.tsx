import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./app/Layout";
import { BacktestDetailPage } from "./pages/BacktestDetailPage";
import { ChartPage } from "./pages/ChartPage";
import { ExperimentsPage } from "./pages/ExperimentsPage";
import { FactorsPage } from "./pages/FactorsPage";
import { FinancePage } from "./pages/FinancePage";
import { HealthPage } from "./pages/HealthPage";
import { JobsPage } from "./pages/JobsPage";
import { JudgmentPage } from "./pages/JudgmentPage";
import { MonitorPage } from "./pages/MonitorPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PaperPage } from "./pages/PaperPage";
import { ResearchPage } from "./pages/ResearchPage";
import { SignalsPage } from "./pages/SignalsPage";
import { TradePage } from "./pages/TradePage";
import { UniversePage } from "./pages/UniversePage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<OverviewPage />} />
          <Route path="trade" element={<TradePage />} />
          <Route path="chart" element={<ChartPage />} />
          <Route path="chart/:code" element={<ChartPage />} />
          <Route path="research" element={<ResearchPage />} />
          <Route path="research/experiments" element={<ExperimentsPage />} />
          <Route path="research/signals" element={<SignalsPage />} />
          <Route path="research/factors" element={<FactorsPage />} />
          <Route path="research/universe" element={<UniversePage />} />
          <Route path="research/judgment" element={<JudgmentPage />} />
          <Route path="research/judgment/:code" element={<JudgmentPage />} />
          <Route path="research/backtests/:runId" element={<BacktestDetailPage />} />
          <Route path="data/health" element={<HealthPage />} />
          <Route path="data/finance" element={<FinancePage />} />
          <Route path="ops/monitor" element={<MonitorPage />} />
          <Route path="ops/jobs" element={<JobsPage />} />
          <Route path="paper" element={<PaperPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
