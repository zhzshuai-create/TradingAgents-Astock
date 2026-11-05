import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import {
  createMemoryRouter,
  RouterProvider,
  useLocation,
  useParams,
} from "react-router-dom";
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import type {
  JobDetail,
  JobStage,
  JobStatus,
  StageId,
  StageReport,
} from "../../api/types";
import { JobDetailPage } from "./JobDetailPage";

const streamState = vi.hoisted(() => ({
  current: { reconnecting: false, expired: false },
}));

vi.mock("./useJobStream", () => ({
  useJobStream: () => streamState.current,
}));

const ORIGIN = "http://localhost:3000";
const STAGE_URL = `${ORIGIN}/api/v1/jobs/:jobId/stages/:stageId`;

const STAGE_SPECS: Array<[StageId, string]> = [
  ["market", "技术分析"],
  ["social", "情绪分析"],
  ["news", "新闻舆情"],
  ["fundamentals", "基本面"],
  ["policy", "政策分析"],
  ["hot_money", "游资追踪"],
  ["lockup", "解禁监控"],
  ["quality_gate", "质量门控"],
  ["debate", "多空辩论"],
  ["trader", "交易决策"],
  ["risk", "风控评估"],
  ["pm", "最终决策"],
];

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

let stageRequests: string[] = [];
let detailRequests = 0;
beforeEach(() => {
  stageRequests = [];
  detailRequests = 0;
  streamState.current = { reconnecting: false, expired: false };
});

function makeStages(
  overrides: Partial<Record<StageId, Partial<JobStage>>> = {},
): JobStage[] {
  return STAGE_SPECS.map(([id, name], index) => ({
    id,
    name,
    index: index + 1,
    status: "pending",
    started_at: null,
    finished_at: null,
    duration_ms: null,
    ...overrides[id],
  }));
}

function done(
  overrides: Partial<JobStage> = {},
): Partial<JobStage> {
  return {
    status: "done",
    started_at: "2026-11-05T09:03:00+08:00",
    finished_at: "2026-11-05T09:04:00+08:00",
    duration_ms: 60_000,
    ...overrides,
  };
}

function job(overrides: Partial<JobDetail> = {}): JobDetail {
  const baseStages = overrides.stages ?? makeStages();
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
    current_stage: null,
    stages: baseStages,
    stats: { model_calls: 2, tokens_in: 12_345, tokens_out: 678, elapsed_ms: 90_000 },
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
    reconcile_notes: [],
    ...overrides,
  };
}

interface StubResult {
  body: unknown;
  status?: number;
}

function serveDetail(result: StubResult | (() => StubResult)): void {
  server.use(
    http.get(`${ORIGIN}/api/v1/jobs/:jobId`, () => {
      detailRequests += 1;
      const next = typeof result === "function" ? result() : result;
      return HttpResponse.json(
        next.body as Parameters<typeof HttpResponse.json>[0],
        { status: next.status ?? 200 },
      );
    }),
  );
}

function reportFor(stageId: string): StageReport {
  const spec = STAGE_SPECS.find(([id]) => id === stageId);
  const index = spec === undefined ? 1 : STAGE_SPECS.indexOf(spec) + 1;
  const markdown = `## ${spec?.[1] ?? stageId} 报告\n\n第 ${index} 阶段的分析内容。`;
  return {
    job_id: "job-1",
    stage_id: (spec?.[0] ?? "market") as StageId,
    stage_name: spec?.[1] ?? "阶段",
    index,
    status: "done",
    markdown,
    truncated: false,
    full_length: markdown.length,
    updated_at: "2026-11-05T09:04:00+08:00",
  };
}

function serveStages(
  bodyFor: (stageId: string) => StageReport | StubResult = reportFor,
): void {
  server.use(
    http.get(STAGE_URL, ({ params }) => {
      const stageId = String(params.stageId);
      stageRequests.push(stageId);
      const result = bodyFor(stageId);
      const stub =
        "body" in result && typeof result.body !== "string"
          ? (result as StubResult)
          : { body: result, status: 200 };
      return HttpResponse.json(
        stub.body as Parameters<typeof HttpResponse.json>[0],
        { status: stub.status ?? 200 },
      );
    }),
  );
}

function LocationProbe() {
  const location = useLocation();
  const { jobId = "", reportId = "" } = useParams();
  return (
    <output data-testid="location">
      {location.pathname} {jobId} {reportId}
    </output>
  );
}

function renderDetail(jobId = "job-1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: "/jobs/:jobId", element: <JobDetailPage /> },
      { path: "/jobs", element: <LocationProbe /> },
      { path: "/reports/:reportId", element: <LocationProbe /> },
    ],
    { initialEntries: [`/jobs/${jobId}`] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("WEB-11 job detail", () => {
  it("renders 12 stages in 7 + 5 groups and marks the current one", async () => {
    serveDetail({
      body: job({
        current_stage: {
          id: "news",
          name: "新闻舆情",
          index: 3,
          total: 12,
          status: "active",
        },
        stages: makeStages({ news: { status: "active" } }),
      }),
    });
    serveStages();
    renderDetail();

    const analysis = await screen.findByTestId("stage-group-analysis");
    const flow = await screen.findByTestId("stage-group-flow");
    expect(within(analysis).getAllByRole("button")).toHaveLength(7);
    expect(within(flow).getAllByRole("button")).toHaveLength(5);
    expect(screen.getByTestId("stage-news")).toHaveAttribute(
      "aria-current",
      "step",
    );
    expect(screen.getByTestId("stage-market")).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("auto-expands the most recently finished stage only", async () => {
    serveDetail({
      body: job({
        stages: makeStages({
          market: done({ finished_at: "2026-11-05T09:03:30+08:00" }),
          social: done({ finished_at: "2026-11-05T09:04:00+08:00" }),
          news: done({ finished_at: "2026-11-05T09:05:00+08:00" }),
        }),
      }),
    });
    serveStages();
    renderDetail();

    expect(await screen.findByTestId("stage-report-body")).toBeVisible();
    expect(stageRequests).toEqual(["news"]);
    expect(screen.getByTestId("stage-report-toggle-news")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByTestId("stage-report-toggle-market")).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("shows 尚未产出 for active and skipped stages without requesting them", async () => {
    serveDetail({
      body: job({
        stages: makeStages({
          market: done(),
          social: { status: "active" },
          quality_gate: { status: "skipped" },
        }),
      }),
    });
    serveStages();
    renderDetail();

    const user = userEvent.setup();
    await screen.findByTestId("stage-report-body");
    await user.click(screen.getByTestId("stage-report-toggle-quality_gate"));

    expect(await screen.findByText("尚未产出")).toBeVisible();
    expect(stageRequests).toEqual(["market"]);
  });

  it("previews a long report and expands the full text without another request", async () => {
    const markdown = Array.from(
      { length: 18 },
      (_, index) => `第 ${index + 1} 段内容`,
    ).join("\n\n");
    serveDetail({
      body: job({ stages: makeStages({ market: done() }) }),
    });
    serveStages(() => ({
      ...reportFor("market"),
      markdown,
      full_length: markdown.length,
    }));
    renderDetail();

    const user = userEvent.setup();
    expect(await screen.findByText("第 1 段内容")).toBeVisible();
    expect(screen.queryByText("第 18 段内容")).toBeNull();

    await user.click(screen.getByTestId("stage-report-expand"));
    expect(await screen.findByText("第 18 段内容")).toBeVisible();
    expect(stageRequests).toEqual(["market"]);
  });

  it("notes a truncated stage report", async () => {
    serveDetail({
      body: job({ stages: makeStages({ market: done() }) }),
    });
    serveStages(() => ({
      ...reportFor("market"),
      truncated: true,
      full_length: 200_000,
    }));
    renderDetail();

    expect(await screen.findByTestId("stage-report-truncated")).toHaveTextContent(
      "报告超过 128 KiB，仅显示前 128 KiB。",
    );
  });

  it("drops raw HTML and opens external links safely", async () => {
    const markdown = [
      "## 安全测试",
      "",
      '<script>window.__pwned = 1</script>',
      '<img src="x" onerror="window.__pwned = 2">',
      "",
      "[外部报告](https://example.com/report)",
    ].join("\n");
    serveDetail({
      body: job({ stages: makeStages({ market: done() }) }),
    });
    serveStages(() => ({
      ...reportFor("market"),
      markdown,
      full_length: markdown.length,
    }));
    renderDetail();

    const body = await screen.findByTestId("stage-report-body");
    expect(body.querySelector("script")).toBeNull();
    expect(body.querySelector("img")).toBeNull();
    expect((window as { __pwned?: number }).__pwned).toBeUndefined();
    const link = screen.getByRole("link", { name: "外部报告" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("keeps a stage report failure inside that stage", async () => {
    serveDetail({
      body: job({ stages: makeStages({ market: done() }) }),
    });
    let attempts = 0;
    serveStages(() => {
      attempts += 1;
      return attempts === 1
        ? {
            body: {
              error: { code: "internal_error", message: "阶段报告读取失败" },
            },
            status: 500,
          }
        : reportFor("market");
    });
    renderDetail();

    const user = userEvent.setup();
    expect(await screen.findByTestId("stage-report-error")).toHaveTextContent(
      "阶段报告读取失败",
    );
    expect(screen.getByTestId("job-header")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByTestId("stage-report-body")).toBeVisible();
  });

  it("shows safe failed copy", async () => {
    serveDetail({
      body: job({
        status: "failed",
        error: { code: "internal_error", message: "模型调用失败" },
        allowed_actions: ["retry", "reanalyze"],
      }),
    });
    serveStages();
    renderDetail();

    expect(await screen.findByTestId("job-notice")).toHaveTextContent(
      "模型调用失败",
    );
  });

  it("keeps interrupted work out of running language", async () => {
    serveDetail({
      body: job({
        status: "interrupted",
        allowed_actions: ["resume_from_checkpoint", "retry", "reanalyze"],
      }),
    });
    serveStages();
    renderDetail();

    await screen.findByTestId("job-header");
    const page = screen.getByTestId("page-job-detail");
    expect(within(page).getByText("任务已中断")).toBeVisible();
    expect(page.textContent).not.toContain("运行中");
    expect(page.textContent).not.toContain("进行中");
  });

  const notices: Array<[JobStatus, string]> = [
    ["queued", "等待 Worker 认领"],
    ["pause_requested", "将在当前阶段结束后生效"],
    ["cancel_requested", "当前阶段结束后生效"],
  ];

  it.each(notices)("shows the %s status notice", async (status, copy) => {
    serveDetail({ body: job({ status }) });
    serveStages();
    renderDetail();
    expect(await screen.findByTestId("job-notice")).toHaveTextContent(copy);
    cleanup();
  });

  it("renders a 404 page with only a route back to the list", async () => {
    serveDetail({
      body: { error: { code: "job_not_found", message: "没有找到这个任务" } },
      status: 404,
    });
    serveStages();
    renderDetail("missing");

    expect(
      await screen.findByRole("heading", { name: "没有找到这个任务" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "返回任务列表" })).toHaveAttribute(
      "href",
      "/jobs",
    );
    expect(screen.queryByRole("button", { name: "重试" })).toBeNull();
    expect(stageRequests).toEqual([]);
  });

  it("offers a retry for non-404 detail errors", async () => {
    let attempts = 0;
    serveDetail(() => {
      attempts += 1;
      return attempts === 1
        ? {
            body: {
              error: { code: "internal_error", message: "服务暂时不可用" },
            },
            status: 500,
          }
        : { body: job() };
    });
    serveStages();
    renderDetail();

    const user = userEvent.setup();
    expect(await screen.findByTestId("job-detail-error")).toHaveTextContent(
      "服务暂时不可用",
    );
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByTestId("job-header")).toBeVisible();
    expect(detailRequests).toBe(2);
  });

  it("renders stats, including a zero elapsed time", async () => {
    serveDetail({
      body: job({
        stats: {
          model_calls: 12,
          tokens_in: 182_430,
          tokens_out: 41_208,
          elapsed_ms: 0,
        },
      }),
    });
    serveStages();
    renderDetail();

    expect(await screen.findByTestId("stat-model-calls")).toHaveTextContent(
      "12",
    );
    expect(screen.getByTestId("stat-tokens-in")).toHaveTextContent("182,430");
    expect(screen.getByTestId("stat-tokens-out")).toHaveTextContent("41,208");
    expect(screen.getByTestId("stat-elapsed")).toHaveTextContent("—");
  });

  it("scrolls to a stage report when a stage is selected on desktop", async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    serveDetail({
      body: job({ stages: makeStages({ market: done() }) }),
    });
    serveStages();
    renderDetail();

    const user = userEvent.setup();
    await screen.findByTestId("stage-report-body");
    await user.click(screen.getByTestId("stage-social"));
    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "start",
    });
    expect(screen.getByTestId("stage-report-toggle-social")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });
});

describe("WEB-14 allowed actions and report entry", () => {
  it("does not render an action group when allowed_actions is empty", async () => {
    serveDetail({ body: job({ allowed_actions: [] }) });
    serveStages();
    renderDetail();

    await screen.findByTestId("job-header");
    expect(screen.queryByTestId("job-actions")).toBeNull();
  });

  it("renders enabled action buttons for the server actions", async () => {
    serveDetail({
      body: job({ allowed_actions: ["pause", "cancel"] }),
    });
    serveStages();
    renderDetail();

    await screen.findByTestId("job-header");
    expect(screen.getByTestId("job-action-pause")).toBeEnabled();
    expect(screen.getByTestId("job-action-cancel")).toBeEnabled();
    expect(screen.getByTestId("job-action-pause")).toHaveTextContent("暂停");
    expect(screen.getByTestId("job-action-cancel")).toHaveTextContent("取消");
  });

  it("shows 打开报告 only when report_id is present", async () => {
    serveDetail({
      body: job({
        status: "succeeded",
        report_id: "report-1",
        allowed_actions: ["retry", "reanalyze"],
      }),
    });
    serveStages();
    renderDetail();

    expect(await screen.findByTestId("job-open-report")).toHaveAttribute(
      "href",
      "/reports/report-1",
    );
  });

  it("hides 打开报告 and explains when a succeeded job has no report", async () => {
    serveDetail({
      body: job({
        status: "succeeded",
        report_id: null,
        allowed_actions: ["retry", "reanalyze"],
      }),
    });
    serveStages();
    renderDetail();

    expect(await screen.findByTestId("job-notice")).toHaveTextContent(
      "报告不可用",
    );
    expect(screen.queryByTestId("job-open-report")).toBeNull();
  });
});

describe("WEB-12 event stream banners", () => {
  it("shows the reconnect banner while the stream is retrying", async () => {
    streamState.current = { reconnecting: true, expired: false };
    serveDetail({ body: job() });
    serveStages();
    renderDetail();

    expect(
      await screen.findByTestId("job-stream-reconnecting"),
    ).toHaveTextContent("正在重连，阶段可能延迟");
    expect(screen.queryByTestId("job-stream-expired")).toBeNull();
  });

  it("asks for a refresh when the cursor expired and stops showing the reconnect copy", async () => {
    streamState.current = { reconnecting: false, expired: true };
    serveDetail({ body: job() });
    serveStages();
    renderDetail();

    const banner = await screen.findByTestId("job-stream-expired");
    expect(banner).toHaveTextContent("刷新以恢复");
    expect(within(banner).getByRole("button", { name: "刷新" })).toBeVisible();
    expect(screen.queryByTestId("job-stream-reconnecting")).toBeNull();
  });

  it("renders neither banner while the stream is connected", async () => {
    serveDetail({ body: job() });
    serveStages();
    renderDetail();

    await screen.findByTestId("job-header");
    expect(screen.queryByTestId("job-stream-reconnecting")).toBeNull();
    expect(screen.queryByTestId("job-stream-expired")).toBeNull();
  });
});

describe("WEB-11 nine statuses", () => {
  const cases: Array<[JobStatus, string]> = [
    ["queued", "排队中"],
    ["running", "运行中"],
    ["pause_requested", "暂停中"],
    ["paused", "已暂停"],
    ["cancel_requested", "取消中"],
    ["cancelled", "已取消"],
    ["succeeded", "已完成"],
    ["failed", "失败"],
    ["interrupted", "等待人工处理"],
  ];

  it.each(cases)("renders the %s badge as %s", async (status, label) => {
    serveDetail({ body: job({ status }) });
    serveStages();
    renderDetail();

    expect(
      within(await screen.findByTestId("job-header")).getByText(label),
    ).toBeVisible();
    if (status === "interrupted") {
      const page = screen.getByTestId("page-job-detail");
      expect(page.textContent).not.toContain("运行中");
      expect(page.textContent).not.toContain("进行中");
    }
  });
});
