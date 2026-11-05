import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import {
  createMemoryRouter,
  RouterProvider,
  useLocation,
} from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import type { JobStatus, JobSummary } from "../api/types";
import { ActiveJobBar } from "./ActiveJobBar";
import {
  ACTIVE_JOBS_REFETCH_MS,
  activeJobsQueryOptions,
} from "./useActiveJobs";

const ORIGIN = "http://localhost:3000";
const JOBS_URL = `${ORIGIN}/api/v1/jobs`;

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function job(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    job_id: "job-3",
    status: "running",
    pending_action: null,
    ticker_code: "000629",
    ticker_name: "钒钛股份",
    analysis_date: "2026-11-05",
    created_at: "2026-11-05T09:03:00+08:00",
    updated_at: "2026-11-05T09:04:00+08:00",
    started_at: "2026-11-05T09:03:01+08:00",
    finished_at: null,
    current_stage: {
      id: "market",
      name: "技术分析",
      index: 1,
      total: 12,
      status: "active",
    },
    stats: { model_calls: 1, tokens_in: 10, tokens_out: 5, elapsed_ms: 1000 },
    report_id: null,
    error: null,
    config_digest: "hash",
    graph_version: "graph-v1",
    retry_of_job_id: null,
    resume_of_job_id: null,
    resume_from_stage: null,
    allowed_actions: ["pause", "cancel"],
    links: {
      self: "/api/v1/jobs/job-3",
      events: "/api/v1/jobs/job-3/events",
      report: null,
    },
    ...overrides,
  };
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}</output>;
}

function renderBar() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: (
          <>
            <ActiveJobBar />
            <LocationProbe />
          </>
        ),
      },
      { path: "/jobs/:jobId", element: <LocationProbe /> },
      { path: "/jobs", element: <LocationProbe /> },
    ],
    { initialEntries: ["/"] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { client, router };
}

function listHandler(items: JobSummary[] | (() => JobSummary[])) {
  return http.get(JOBS_URL, () =>
    HttpResponse.json({
      items: typeof items === "function" ? items() : items,
      next_cursor: null,
    }),
  );
}

describe("WEB-07 active job bar", () => {
  it("renders nothing when there is no active job", async () => {
    server.use(listHandler([]));
    renderBar();

    await waitFor(() =>
      expect(screen.queryByTestId("active-job-bar")).not.toBeInTheDocument(),
    );
  });

  it("ignores terminal jobs even if the server returns them", async () => {
    server.use(
      listHandler([
        job({ status: "succeeded" }),
        job({ job_id: "job-2", status: "failed" }),
      ]),
    );
    renderBar();

    await waitFor(() =>
      expect(screen.queryByTestId("active-job-bar")).not.toBeInTheDocument(),
    );
  });

  it("shows the latest job with its name and stage, and links to detail", async () => {
    server.use(listHandler([job()]));
    const { router } = renderBar();

    const bar = await screen.findByTestId("active-job-bar");
    expect(within(bar).getByText("钒钛股份")).toBeInTheDocument();
    expect(within(bar).getByText("000629")).toBeInTheDocument();
    expect(within(bar).getByText("技术分析 1/12")).toBeInTheDocument();

    fireEvent.click(within(bar).getByRole("link", { name: "查看" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/jobs/job-3"));
  });

  it("falls back to the code when the name is unknown", async () => {
    server.use(listHandler([job({ ticker_name: null })]));
    renderBar();

    const bar = await screen.findByTestId("active-job-bar");
    expect(within(bar).getByRole("link", { name: "000629" })).toHaveAttribute(
      "href",
      "/jobs/job-3",
    );
  });

  it("reports how many other jobs are active and links to the list", async () => {
    server.use(
      listHandler([
        job(),
        job({ job_id: "job-2", created_at: "2026-11-05T09:02:00+08:00" }),
        job({ job_id: "job-1", created_at: "2026-11-05T09:01:00+08:00" }),
      ]),
    );
    renderBar();

    const more = await screen.findByRole("link", { name: "还有 2 个" });
    expect(more).toHaveAttribute("href", "/jobs?active=true");
  });

  it("never POSTs to /jobs when the bar is opened", async () => {
    let posts = 0;
    server.use(
      listHandler([job()]),
      http.post(JOBS_URL, () => {
        posts += 1;
        return HttpResponse.json({}, { status: 201 });
      }),
    );
    renderBar();

    const bar = await screen.findByTestId("active-job-bar");
    fireEvent.click(within(bar).getByRole("link", { name: "查看" }));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/jobs/job-3"),
    );
    expect(posts).toBe(0);
  });

  it("disappears when the latest job reaches a terminal state", async () => {
    let status: JobStatus = "running";
    server.use(listHandler(() => [job({ status })]));
    const { client } = renderBar();

    await screen.findByTestId("active-job-bar");
    status = "succeeded";
    await client.invalidateQueries({ queryKey: ["jobs"] });

    await waitFor(() =>
      expect(screen.queryByTestId("active-job-bar")).not.toBeInTheDocument(),
    );
  });

  it("refreshes the active list every ten seconds", () => {
    expect(ACTIVE_JOBS_REFETCH_MS).toBe(10_000);
    expect(activeJobsQueryOptions().refetchInterval).toBe(10_000);
  });
});
