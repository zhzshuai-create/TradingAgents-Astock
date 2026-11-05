import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import {
  act,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
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
} from "vitest";

import type { JobDetail } from "../../api/types";
import { jobDetailQuery, queryKeys } from "../../lib/query";
import { StatusHeader } from "./StatusHeader";

const ORIGIN = "http://localhost:3000";
const ACTION_URL = `${ORIGIN}/api/v1/jobs/:jobId/actions`;
const RETRY_URL = `${ORIGIN}/api/v1/jobs/:jobId/retry`;
const DETAIL_URL = `${ORIGIN}/api/v1/jobs/:jobId`;

function job(overrides: Partial<JobDetail> = {}): JobDetail {
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
    stages: [],
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

function apiError(status: number, code: string, message: string) {
  return HttpResponse.json(
    { error: { code, message, details: {} } },
    { status },
  );
}

let currentJob: JobDetail;
let detailRequests = 0;
let actionRequests: string[] = [];
let retryRequests: Array<{ mode: string; key: string | null }> = [];

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

beforeEach(() => {
  currentJob = job();
  detailRequests = 0;
  actionRequests = [];
  retryRequests = [];
  server.use(
    http.get(DETAIL_URL, ({ params }) => {
      detailRequests += 1;
      const requested = String(params.jobId);
      if (requested === currentJob.job_id) {
        return HttpResponse.json(currentJob);
      }
      return HttpResponse.json(
        job({ job_id: requested, status: "queued", allowed_actions: [] }),
      );
    }),
  );
});

function serveAction(
  handler: (action: string) => ReturnType<typeof HttpResponse.json>,
): void {
  server.use(
    http.post(ACTION_URL, async ({ request }) => {
      const body = (await request.json()) as { action: string };
      actionRequests.push(body.action);
      return handler(body.action);
    }),
  );
}

function serveRetry(
  handler: (mode: string) => ReturnType<typeof HttpResponse.json> | Response,
): void {
  server.use(
    http.post(RETRY_URL, async ({ request }) => {
      const body = (await request.json()) as { mode: string };
      retryRequests.push({
        mode: body.mode,
        key: request.headers.get("Idempotency-Key"),
      });
      return handler(body.mode);
    }),
  );
}

function Harness() {
  const { jobId = "job-1" } = useParams();
  const fallback =
    jobId === currentJob.job_id
      ? currentJob
      : job({ job_id: jobId, status: "queued", allowed_actions: [] });
  const query = useQuery({ ...jobDetailQuery(jobId), initialData: fallback });
  return (
    <>
      <output data-testid="location">{jobId}</output>
      <StatusHeader job={query.data ?? fallback} />
    </>
  );
}

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="probe">
      {location.pathname}
      {location.search}
    </output>
  );
}

function renderActions() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: "/jobs/:jobId", element: <Harness /> },
      { path: "/workbench", element: <LocationProbe /> },
    ],
    { initialEntries: ["/jobs/job-1"] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, client };
}

describe("WEB-13 job actions", () => {
  it("renders only the actions the server allows", async () => {
    currentJob = job({ allowed_actions: ["pause", "cancel"] });
    renderActions();

    expect(await screen.findByTestId("job-action-pause")).toHaveTextContent(
      "暂停",
    );
    expect(screen.getByTestId("job-action-cancel")).toHaveTextContent("取消");
    expect(screen.queryByTestId("job-action-retry")).toBeNull();
  });

  it("shows 暂停中 only after the server accepts the pause", async () => {
    serveAction(() => {
      currentJob = job({
        status: "pause_requested",
        pending_action: "pause",
        allowed_actions: ["cancel"],
      });
      return HttpResponse.json(
        {
          job_id: "job-1",
          accepted: true,
          action: "pause",
          accepted_at: "2026-11-05T09:05:00+08:00",
          expected_effect: "at_stage_boundary",
          status: "pause_requested",
        },
        { status: 202 },
      );
    });
    const user = userEvent.setup();
    renderActions();

    await user.click(await screen.findByTestId("job-action-pause"));
    await waitFor(() =>
      expect(screen.queryByTestId("job-action-pause")).toBeNull(),
    );
    expect(
      within(screen.getByTestId("job-header")).getByText("暂停中"),
    ).toBeVisible();
    expect(screen.getByTestId("job-action-cancel")).toBeVisible();
    expect(actionRequests).toEqual(["pause"]);
    expect(detailRequests).toBeGreaterThan(1);
  });

  it("fetches the new allowed_actions when the stream changes status", async () => {
    currentJob = job({
      status: "pause_requested",
      pending_action: "pause",
      allowed_actions: ["cancel"],
    });
    const { client } = renderActions();
    await screen.findByTestId("job-action-cancel");

    currentJob = job({
      status: "paused",
      allowed_actions: ["resume", "cancel"],
    });
    act(() => {
      client.setQueryData<JobDetail>(
        queryKeys.job("job-1"),
        (current) =>
          current === undefined
            ? current
            : { ...current, status: "paused", pending_action: null },
      );
    });

    expect(await screen.findByTestId("job-action-resume")).toBeVisible();
    expect(screen.queryByTestId("job-action-pause")).toBeNull();
    expect(screen.getByTestId("job-action-cancel")).toBeVisible();
  });

  it("treats already_pending as accepted and refreshes without an error", async () => {
    currentJob = job({
      status: "pause_requested",
      pending_action: "pause",
      allowed_actions: ["cancel"],
    });
    serveAction(() =>
      HttpResponse.json({
        job_id: "job-1",
        accepted: false,
        reason: "already_pending",
        status: "pause_requested",
      }),
    );
    const user = userEvent.setup();
    renderActions();

    await user.click(await screen.findByTestId("job-action-cancel"));
    await user.click(await screen.findByTestId("job-cancel-confirm"));
    await waitFor(() => expect(detailRequests).toBeGreaterThan(1));
    expect(screen.queryByTestId("job-action-error")).toBeNull();
    expect(actionRequests).toEqual(["cancel"]);
  });

  it("confirms cancel with safe focus and Esc before sending anything", async () => {
    serveAction(() => {
      currentJob = job({
        status: "cancel_requested",
        pending_action: "cancel",
        allowed_actions: [],
      });
      return HttpResponse.json(
        {
          job_id: "job-1",
          accepted: true,
          action: "cancel",
          accepted_at: "2026-11-05T09:05:00+08:00",
          expected_effect: "at_stage_boundary",
          status: "cancel_requested",
        },
        { status: 202 },
      );
    });
    const user = userEvent.setup();
    renderActions();

    await user.click(await screen.findByTestId("job-action-cancel"));
    const dialog = await screen.findByTestId("job-cancel-dialog");
    expect(dialog).toHaveTextContent("模型费用不退");
    expect(dialog).toHaveTextContent("不会生成完整报告");
    expect(screen.getByTestId("job-cancel-dismiss")).toHaveFocus();

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByTestId("job-cancel-dialog")).toBeNull(),
    );
    expect(actionRequests).toEqual([]);

    await user.click(screen.getByTestId("job-action-cancel"));
    await user.click(await screen.findByTestId("job-cancel-confirm"));
    await waitFor(() =>
      expect(screen.queryByTestId("job-cancel-dialog")).toBeNull(),
    );
    expect(actionRequests).toEqual(["cancel"]);
    expect(screen.queryByTestId("job-actions")).toBeNull();
  });

  it("retries once with a fresh idempotency key and opens the new job", async () => {
    currentJob = job({
      status: "failed",
      allowed_actions: ["retry", "reanalyze"],
    });
    serveRetry(() => {
      const next = job({
        job_id: "job-2",
        status: "queued",
        retry_of_job_id: "job-1",
        allowed_actions: [],
      });
      return HttpResponse.json(next, { status: 201 });
    });
    const user = userEvent.setup();
    renderActions();

    await user.dblClick(await screen.findByTestId("job-action-retry"));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("job-2"),
    );
    expect(retryRequests).toHaveLength(1);
    expect(retryRequests[0].mode).toBe("same_config");
    expect(retryRequests[0].key).toBeTruthy();
  });

  it("opens the existing job when retry answers 200 with X-Existing-Job", async () => {
    currentJob = job({
      status: "failed",
      allowed_actions: ["retry", "reanalyze"],
    });
    serveRetry(() =>
      HttpResponse.json(
        job({ job_id: "job-9", status: "queued", allowed_actions: [] }),
        { status: 200, headers: { "X-Existing-Job": "job-9" } },
      ),
    );
    const user = userEvent.setup();
    renderActions();

    await user.click(await screen.findByTestId("job-action-retry"));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("job-9"),
    );
    expect(retryRequests).toHaveLength(1);
  });

  it("hides resume and retry after a fingerprint mismatch", async () => {
    currentJob = job({
      status: "interrupted",
      allowed_actions: ["resume_from_checkpoint", "retry", "reanalyze"],
    });
    serveRetry(() =>
      apiError(
        409,
        "resume_fingerprint_mismatch",
        "配置已变化，无法从检查点继续",
      ),
    );
    const user = userEvent.setup();
    renderActions();

    await user.click(await screen.findByTestId("job-action-resume_from_checkpoint"));
    expect(await screen.findByTestId("job-action-error")).toHaveTextContent(
      "配置已变化",
    );
    expect(await screen.findByTestId("job-action-notice")).toHaveTextContent(
      "只能重新分析",
    );
    expect(screen.queryByTestId("job-action-resume_from_checkpoint")).toBeNull();
    expect(screen.queryByTestId("job-action-retry")).toBeNull();
    expect(screen.getByTestId("job-action-reanalyze")).toBeVisible();
  });

  it("refreshes on illegal_transition instead of showing an error", async () => {
    serveAction(() => {
      currentJob = job({
        status: "succeeded",
        report_id: "report-1",
        allowed_actions: ["retry", "reanalyze"],
      });
      return apiError(409, "illegal_transition", "当前状态不支持这个操作");
    });
    const user = userEvent.setup();
    renderActions();

    await user.click(await screen.findByTestId("job-action-pause"));
    expect(await screen.findByTestId("job-open-report")).toHaveAttribute(
      "href",
      "/reports/report-1",
    );
    expect(screen.queryByTestId("job-action-error")).toBeNull();
    expect(detailRequests).toBeGreaterThan(1);
  });

  it("keeps the same retry key after a network failure", async () => {
    currentJob = job({
      status: "failed",
      allowed_actions: ["retry", "reanalyze"],
    });
    let attempt = 0;
    serveRetry(() => {
      attempt += 1;
      if (attempt === 1) {
        return HttpResponse.error();
      }
      return HttpResponse.json(
        job({ job_id: "job-2", status: "queued", allowed_actions: [] }),
        { status: 201 },
      );
    });
    const user = userEvent.setup();
    renderActions();

    await user.click(await screen.findByTestId("job-action-retry"));
    expect(await screen.findByTestId("job-action-error")).toHaveTextContent(
      "网络连接失败",
    );
    await user.click(screen.getByTestId("job-action-retry"));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("job-2"),
    );
    expect(retryRequests).toHaveLength(2);
    expect(retryRequests[0].key).toBe(retryRequests[1].key);
  });

  it("sends reanalyze to the launcher instead of creating a job", async () => {
    currentJob = job({
      status: "failed",
      allowed_actions: ["retry", "reanalyze"],
    });
    const user = userEvent.setup();
    renderActions();

    await user.click(await screen.findByTestId("job-action-reanalyze"));
    expect(await screen.findByTestId("probe")).toHaveTextContent(
      "/workbench?launch=1&ticker=000629",
    );
    expect(actionRequests).toEqual([]);
    expect(retryRequests).toEqual([]);
  });
});
