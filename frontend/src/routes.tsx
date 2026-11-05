import { Navigate, type RouteObject } from "react-router-dom";

import { WorkbenchPage } from "./features/workbench/WorkbenchPage";
import { InvalidTickerPage } from "./pages/InvalidTickerPage";
import { JobDetailPage } from "./pages/JobDetailPage";
import { JobsPage } from "./pages/JobsPage";
import { JournalPage } from "./pages/JournalPage";
import { MarketPage } from "./pages/MarketPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ReportDetailPage } from "./pages/ReportDetailPage";
import { ReportsPage } from "./pages/ReportsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { StockPage } from "./pages/StockPage";
import { AppShell } from "./shell/AppShell";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/workbench" replace /> },
      { path: "workbench", element: <WorkbenchPage /> },
      { path: "market", element: <MarketPage /> },
      { path: "stocks/:ticker", element: <StockPage /> },
      { path: "stocks", element: <InvalidTickerPage ticker="" /> },
      { path: "jobs", element: <JobsPage /> },
      { path: "jobs/:jobId", element: <JobDetailPage /> },
      { path: "reports", element: <ReportsPage /> },
      { path: "reports/:reportId", element: <ReportDetailPage /> },
      { path: "journal", element: <JournalPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
