import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, type RouteObject } from "react-router-dom";

import { AppShell } from "./shell/AppShell";
import { PageFallback } from "./shell/PageFallback";

/**
 * One dynamic import per page keeps the entry chunk inside the P4 budget.
 * ``PAGE_CHUNKS`` is exported so the route-split test can assert every page
 * is a lazy component (DS-07).
 */
export const PAGE_CHUNKS = {
  workbench: lazy(() =>
    import("./features/workbench/WorkbenchPage").then((module) => ({
      default: module.WorkbenchPage,
    })),
  ),
  market: lazy(() =>
    import("./pages/MarketPage").then((module) => ({
      default: module.MarketPage,
    })),
  ),
  stock: lazy(() =>
    import("./pages/StockPage").then((module) => ({
      default: module.StockPage,
    })),
  ),
  invalidTicker: lazy(() =>
    import("./pages/InvalidTickerPage").then((module) => ({
      default: module.InvalidTickerPage,
    })),
  ),
  jobs: lazy(() =>
    import("./pages/JobsPage").then((module) => ({
      default: module.JobsPage,
    })),
  ),
  jobDetail: lazy(() =>
    import("./pages/JobDetailPage").then((module) => ({
      default: module.JobDetailPage,
    })),
  ),
  reports: lazy(() =>
    import("./pages/ReportsPage").then((module) => ({
      default: module.ReportsPage,
    })),
  ),
  reportDetail: lazy(() =>
    import("./pages/ReportDetailPage").then((module) => ({
      default: module.ReportDetailPage,
    })),
  ),
  journal: lazy(() =>
    import("./pages/JournalPage").then((module) => ({
      default: module.JournalPage,
    })),
  ),
  settings: lazy(() =>
    import("./pages/SettingsPage").then((module) => ({
      default: module.SettingsPage,
    })),
  ),
  notFound: lazy(() =>
    import("./pages/NotFoundPage").then((module) => ({
      default: module.NotFoundPage,
    })),
  ),
} as const;

function page(node: ReactNode): ReactNode {
  return <Suspense fallback={<PageFallback />}>{node}</Suspense>;
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/workbench" replace /> },
      { path: "workbench", element: page(<PAGE_CHUNKS.workbench />) },
      { path: "market", element: page(<PAGE_CHUNKS.market />) },
      { path: "stocks/:ticker", element: page(<PAGE_CHUNKS.stock />) },
      {
        path: "stocks",
        element: page(<PAGE_CHUNKS.invalidTicker ticker="" />),
      },
      { path: "jobs", element: page(<PAGE_CHUNKS.jobs />) },
      { path: "jobs/:jobId", element: page(<PAGE_CHUNKS.jobDetail />) },
      { path: "reports", element: page(<PAGE_CHUNKS.reports />) },
      {
        path: "reports/:reportId",
        element: page(<PAGE_CHUNKS.reportDetail />),
      },
      { path: "journal", element: page(<PAGE_CHUNKS.journal />) },
      { path: "settings", element: page(<PAGE_CHUNKS.settings />) },
      { path: "*", element: page(<PAGE_CHUNKS.notFound />) },
    ],
  },
];
