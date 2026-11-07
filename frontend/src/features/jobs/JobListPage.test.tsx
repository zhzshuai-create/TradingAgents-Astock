import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import {
  createMemoryRouter,
  RouterProvider,
  useLocation,
} from "react-router-dom";
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
} from "vitest";

import type { JobListResponse, JobSummary } from "../../api/types";
import { JobListPage } from "./JobListPage";
import { JOB_STATUS_ORDER } from "./listParams";

const ORIGIN = "http://localhost:3000";
const JOBS_URL = `${ORIGIN}/api/v1/jobs`;

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

let requests: URLSearchParams[] = [];
beforeEach(() => {
  requests = [];
  sessionStorage.clear();
  document.getElementById("main-content")?.remove();
});

function job(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    job_id: "job-1",
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
      index: 3,
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
      self: "/api/v1/jobs/job-1",
      events: "/api/v1/jobs/job-1/events",
      report: null,
    },
    ...overrides,
  };
}

function page(items: JobSummary[], next: string | null = null): JobListResponse {
  return { items, next_cursor: next };
}

interface StubResult {
  body: unknown;
  status?: number;
}

function serveJobs(handler: (params: URLSearchParams) => StubResult): void {
  server.use(
    http.get(JOBS_URL, ({ request }) => {
      const params = new URL(request.url).searchParams;
      requests.push(params);
      const result = handler(params);
      return HttpResponse.json(
        result.body as Parameters<typeof HttpResponse.json>[0],
        { status: result.status ?? 200 },
      );
    }),
  );
}

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {location.pathname}
      {location.search}
    </output>
  );
}

function renderPage(initialEntry: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: "/jobs", element: <JobListPage /> },
      { path: "/workbench", element: <LocationProbe /> },
      { path: "/jobs/:jobId", element: <LocationProbe /> },
    ],
    { initialEntries: [initialEntry] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

function mountScrollContainer(): HTMLElement {
  // jsdom has no layout, so scrollTop needs a writable stand-in.
  const main = document.createElement("div");
  main.id = "main-content";
  let scrollTop = 0;
  Object.defineProperty(main, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: (value: number) => {
      scrollTop = value;
    },
  });
  document.body.appendChild(main);
  return main;
}

describe("WEB-10 job list", () => {
  it("asks for the first page with limit 20 and no status by default", async () => {
    serveJobs(() => ({ body: page([job()]) }));
    renderPage("/jobs");

    await screen.findByTestId("job-row");
    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    const params = requests[0];
    expect(params.get("limit")).toBe("20");
    expect(params.has("status")).toBe(false);
    expect(params.has("ticker")).toBe(false);
    expect(params.has("date_from")).toBe(false);
    expect(params.has("date_to")).toBe(false);
    expect(params.has("active")).toBe(false);
  });

  it("rebuilds the control state and request from a deep link", async () => {
    serveJobs(() => ({
      body: page([
        job({
          status: "failed",
          error: { code: "model_error", message: "模型调用失败" },
        }),
      ]),
    }));
    const router = renderPage("/jobs?status=failed&ticker=000629");

    await screen.findByTestId("job-row");
    await waitFor(() =>
      expect(router.state.location.search).toBe("?status=failed&ticker=000629"),
    );
    const params = requests[0];
    expect(params.get("status")).toBe("failed");
    expect(params.get("ticker")).toBe("000629");
    expect(screen.getByLabelText("股票代码")).toHaveValue("000629");
    expect(screen.getByRole("checkbox", { name: "失败" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "运行中" })).not.toBeChecked();
  });

  it("writes a comma list for a subset and omits status when all return", async () => {
    serveJobs(() => ({ body: page([job()]) }));
    const router = renderPage("/jobs");

    await screen.findByTestId("job-row");
    const done = screen.getByRole("checkbox", { name: "已完成" });
    expect(done).toBeChecked();
    fireEvent.click(done);

    const expected = JOB_STATUS_ORDER.filter(
      (status) => status !== "succeeded",
    ).join(",");
    await waitFor(() => expect(requests.at(-1)?.get("status")).toBe(expected));
    expect(router.state.location.search).toBe(
      `?status=${encodeURIComponent(expected)}`,
    );

    const before = requests.length;
    fireEvent.click(screen.getByRole("checkbox", { name: "已完成" }));
    await waitFor(() => expect(requests.length).toBeGreaterThan(before));
    expect(requests.at(-1)?.has("status")).toBe(false);
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });

  it("refuses to clear the last selected status", async () => {
    serveJobs(() => ({ body: page([job({ status: "failed" })]) }));
    const router = renderPage("/jobs?status=failed");

    await screen.findByTestId("job-row");
    const failed = screen.getByRole("checkbox", { name: "失败" });
    fireEvent.click(failed);

    await waitFor(() =>
      expect(router.state.location.search).toBe("?status=failed"),
    );
    expect(failed).toBeChecked();
  });

  it("sends only active=true while the activity switch is on", async () => {
    serveJobs(() => ({ body: page([job()]) }));
    const router = renderPage("/jobs");

    await screen.findByTestId("job-row");
    const onlyActive = screen.getByRole("checkbox", { name: "只看活动任务" });
    const before = requests.length;
    fireEvent.click(onlyActive);

    await waitFor(() => expect(requests.length).toBeGreaterThan(before));
    let params = requests.at(-1);
    expect(params?.get("active")).toBe("true");
    expect(params?.has("status")).toBe(false);
    expect(router.state.location.search).toBe("?active=true");
    expect(screen.getByRole("checkbox", { name: "运行中" })).toBeDisabled();

    const earlier = requests.length;
    fireEvent.click(onlyActive);
    await waitFor(() => expect(requests.length).toBeGreaterThan(earlier));
    params = requests.at(-1);
    expect(params?.has("active")).toBe(false);
    expect(screen.getByRole("checkbox", { name: "运行中" })).not.toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "运行中" })).toBeChecked();
  });

  it("drops malformed deep-link values instead of sending them", async () => {
    serveJobs(() => ({ body: page([job()]) }));
    const router = renderPage(
      "/jobs?status=bogus,running&ticker=12&date_from=2026-02-30&date_to=2026-01-01&active=maybe",
    );

    await screen.findByTestId("job-row");
    await waitFor(() =>
      expect(router.state.location.search).toBe(
        "?status=running&date_to=2026-01-01",
      ),
    );
    const params = requests[0];
    expect(params.get("status")).toBe("running");
    expect(params.has("ticker")).toBe(false);
    // The invalid start date is dropped; the valid end date can stand alone.
    expect(params.has("date_from")).toBe(false);
    expect(params.get("date_to")).toBe("2026-01-01");
    expect(params.has("active")).toBe(false);
    expect(screen.getByLabelText("股票代码")).toHaveValue("");
  });

  it("loads more with the server cursor and resets it when a filter changes", async () => {
    serveJobs((params) => {
      if (params.get("cursor") === "c2") {
        return {
          body: page([
            job({
              job_id: "job-2",
              ticker_code: "600519",
              ticker_name: "贵州茅台",
            }),
          ]),
        };
      }
      return { body: page([job()], "c2") };
    });
    const router = renderPage("/jobs");

    await screen.findByTestId("job-row");
    const before = requests.length;
    fireEvent.click(screen.getByRole("button", { name: "加载更多" }));

    await waitFor(() => expect(screen.getAllByTestId("job-row")).toHaveLength(2));
    await waitFor(() => expect(router.state.location.search).toBe("?cursor=c2"));
    expect(requests.length).toBeGreaterThan(before);
    expect(requests.at(-1)?.get("cursor")).toBe("c2");

    fireEvent.click(screen.getByRole("checkbox", { name: "已完成" }));
    await waitFor(() => {
      const params = requests.at(-1);
      expect(params?.has("cursor")).toBe(false);
      expect(params?.has("status")).toBe(true);
    });
    expect(router.state.location.search).not.toContain("cursor=");
  });

  it("keeps loaded rows when loading more fails and retries the same cursor", async () => {
    let nextPageCalls = 0;
    serveJobs((params) => {
      if (params.get("cursor") === "c2") {
        nextPageCalls += 1;
        if (nextPageCalls === 1) {
          return {
            status: 500,
            body: {
              error: { code: "internal_error", message: "服务暂时不可用" },
            },
          };
        }
        return { body: page([job({ job_id: "job-2" })]) };
      }
      return { body: page([job()], "c2") };
    });
    renderPage("/jobs");

    await screen.findByTestId("job-row");
    fireEvent.click(screen.getByRole("button", { name: "加载更多" }));
    expect(
      await screen.findByText("加载更多失败，已加载的任务仍然保留。"),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId("job-row")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(screen.getAllByTestId("job-row")).toHaveLength(2));
    expect(nextPageCalls).toBe(2);
    expect(
      requests.filter((params) => params.get("cursor") === "c2"),
    ).toHaveLength(2);
  });

  it("offers the first analysis when there are no jobs at all", async () => {
    serveJobs(() => ({ body: page([]) }));
    const router = renderPage("/jobs");

    expect(await screen.findByText("还没有分析任务")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "开始一次分析" }));

    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/workbench"),
    );
    expect(router.state.location.search).toBe("?launch=1");
  });

  it("clears the filters when the filtered list is empty", async () => {
    serveJobs(() => ({ body: page([]) }));
    const router = renderPage("/jobs?status=failed&ticker=000629");

    expect(await screen.findByText("没有符合条件的任务")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "清空筛选" }));

    await waitFor(() => expect(router.state.location.search).toBe(""));
    await waitFor(() => expect(requests.at(-1)?.has("status")).toBe(false));
  });

  it("keeps the URL and offers retry when the first page fails", async () => {
    let calls = 0;
    serveJobs(() => {
      calls += 1;
      if (calls === 1) {
        return {
          status: 500,
          body: {
            error: { code: "internal_error", message: "服务暂时不可用" },
          },
        };
      }
      return { body: page([job()]) };
    });
    const router = renderPage("/jobs?status=failed");

    expect(await screen.findByText("服务暂时不可用")).toBeInTheDocument();
    expect(router.state.location.search).toBe("?status=failed");

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByTestId("job-row")).toBeInTheDocument();
    expect(router.state.location.search).toBe("?status=failed");
    expect(calls).toBe(2);
  });

  it("shows safe failed copy and never labels interrupted as running", async () => {
    serveJobs(() => ({
      body: page([
        job({
          job_id: "job-fail",
          status: "failed",
          current_stage: null,
          error: { code: "model_error", message: "模型调用失败" },
        }),
        job({
          job_id: "job-interrupt",
          status: "interrupted",
          current_stage: null,
        }),
      ]),
    }));
    renderPage("/jobs");

    const table = await screen.findByTestId("job-table");
    expect(within(table).getByText("模型调用失败")).toBeInTheDocument();
    expect(within(table).getByText("等待人工处理")).toBeInTheDocument();
    expect(within(table).queryByText("运行中")).not.toBeInTheDocument();
    expect(within(table).queryByText("进行中")).not.toBeInTheDocument();

    const rows = screen.getAllByTestId("job-row");
    expect(within(rows[0]).getByRole("link", { name: "查看" })).toHaveAttribute(
      "href",
      "/jobs/job-fail",
    );
  });

  it("draws a progress bar only when the job has an active stage", async () => {
    serveJobs(() => ({
      body: page([
        job({ job_id: "job-run", status: "running" }),
        job({
          job_id: "job-queue",
          status: "queued",
          current_stage: null,
        }),
      ]),
    }));
    renderPage("/jobs");

    await screen.findByTestId("job-table");
    const rows = screen.getAllByTestId("job-row");
    expect(within(rows[0]).getByTestId("stage-progress")).toBeInTheDocument();
    expect(
      within(rows[1]).queryByTestId("stage-progress"),
    ).not.toBeInTheDocument();
    expect(within(rows[1]).getByText("等待开始")).toBeInTheDocument();
  });

  it("restores the saved scroll position once and clears the key", async () => {
    serveJobs(() => ({ body: page([job()]) }));
    const main = mountScrollContainer();
    sessionStorage.setItem("ta:jobs-scroll:/jobs?status=failed", "1200");

    renderPage("/jobs?status=failed");

    await screen.findByTestId("job-row");
    await waitFor(() => expect(main.scrollTop).toBe(1200));
    expect(sessionStorage.getItem("ta:jobs-scroll:/jobs?status=failed")).toBeNull();
  });

  it("saves the scroll position when the list unmounts", async () => {
    serveJobs(() => ({ body: page([job()]) }));
    const main = mountScrollContainer();
    const router = renderPage("/jobs");

    await screen.findByTestId("job-row");
    main.scrollTop = 640;
    main.dispatchEvent(new Event("scroll"));
    // Removing the list clamps the real container to 0 before cleanup runs.
    main.scrollTop = 0;
    await router.navigate("/workbench");

    await waitFor(() =>
      expect(sessionStorage.getItem("ta:jobs-scroll:/jobs")).toBe("640"),
    );
  });

  it("keeps loaded pages after leaving and coming back", async () => {
    const first = Array.from({ length: 20 }, (_, index) =>
      job({ job_id: `job-${index}` }),
    );
    serveJobs((params) =>
      params.get("cursor") === "c1"
        ? { body: page([job({ job_id: "job-20" })]) }
        : { body: page(first, "c1") },
    );
    const router = renderPage("/jobs");

    await waitFor(() =>
      expect(screen.getAllByTestId("job-row")).toHaveLength(20),
    );
    fireEvent.click(screen.getByRole("button", { name: "加载更多" }));
    await waitFor(() =>
      expect(screen.getAllByTestId("job-row")).toHaveLength(21),
    );
    await waitFor(() =>
      expect(router.state.location.search).toContain("cursor=c1"),
    );

    await router.navigate("/jobs/job-0");
    await screen.findByTestId("location");
    await router.navigate(-1);

    await waitFor(() =>
      expect(screen.getAllByTestId("job-row")).toHaveLength(21),
    );
    // The stale refetch must rebuild both pages, not collapse onto the cursor.
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(screen.getAllByTestId("job-row")).toHaveLength(21);
  });

  it("rebuilds every loaded page from a cursor deep link", async () => {
    const first = Array.from({ length: 20 }, (_, index) =>
      job({ job_id: `job-${index}` }),
    );
    serveJobs((params) =>
      params.get("cursor") === "c1"
        ? { body: page([job({ job_id: "job-20" })]) }
        : { body: page(first, "c1") },
    );
    const router = renderPage(
      "/jobs?status=succeeded&ticker=000629&cursor=c1",
    );

    await waitFor(() =>
      expect(screen.getAllByTestId("job-row")).toHaveLength(21),
    );
    expect(requests.map((params) => params.get("cursor"))).toEqual([
      null,
      "c1",
    ]);
    expect(router.state.location.search).toContain("cursor=c1");
  });
});

describe("CTX-03 job list ticker link", () => {
  it("links every row ticker to the stock workspace", async () => {
    serveJobs(() => ({ body: page([job()]) }));
    renderPage("/jobs");
    const link = await screen.findByTestId("job-ticker-link");
    expect(link).toHaveAttribute("href", "/stocks/000629");
    expect(link).toHaveTextContent("钒钛股份");
  });
});

describe("P5-07 screen reader semantics", () => {
  it("SR-06 captions the job table and uses ticker cells as row headers", async () => {
    serveJobs(() => ({
      body: page([job({ job_id: "job-a" }), job({ job_id: "job-b" })]),
    }));
    renderPage("/jobs");

    const table = await screen.findByTestId("job-table");
    expect(table).toHaveAccessibleName("任务列表");
    expect(table.querySelector("caption")).toHaveTextContent("任务列表");
    const headers = table.querySelectorAll("tbody th[scope='row']");
    expect(headers).toHaveLength(2);
    expect(headers[0]).toHaveTextContent("钒钛股份");
    for (const cell of Array.from(table.querySelectorAll("th"))) {
      expect(cell).toHaveAttribute("scope");
    }
    expect(
      within(screen.getAllByTestId("job-row")[0]).getByTestId("job-ticker-link"),
    ).toHaveAccessibleName(/钒钛股份/);
  });
});
