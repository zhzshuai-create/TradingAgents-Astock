import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { useState } from "react";
import {
  createMemoryRouter,
  RouterProvider,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import type {
  CreateJobRequest,
  JobDetail,
  MarketEnvelope,
  MarketSearchData,
  MetaOptions,
} from "../../api/types";
import { LauncherDialog } from "./LauncherDialog";
import type { TickerSelection } from "./types";

const ORIGIN = "http://localhost:3000";
const META_URL = `${ORIGIN}/api/v1/meta/options`;
const SEARCH_URL = `${ORIGIN}/api/v1/market/search`;
const JOBS_URL = `${ORIGIN}/api/v1/jobs`;

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const META: MetaOptions = {
  app_version: "0.9.0",
  server_time: "2026-11-05T09:30:00+08:00",
  default_analysis_date: "2026-11-05",
  llm_profiles: [
    { id: "deepseek-default", label: "DeepSeek 默认" },
    { id: "qwen-max", label: "通义千问 Max" },
  ],
  stage_toggles: [
    { id: "policy", label: "政策分析", default: true },
    { id: "hot_money", label: "游资分析", default: true },
    { id: "lockup", label: "解禁分析", default: true },
  ],
  limits: { max_active_jobs: 1, max_date_ahead_days: 0 },
  journal: { available: false, entry_url: "http://127.0.0.1:8502", reason: null },
  contract_version: "api-v1",
};

const JOB: JobDetail = {
  job_id: "job-1",
  status: "queued",
  pending_action: null,
  ticker_code: "300750",
  ticker_name: "宁德时代",
  analysis_date: "2026-11-05",
  created_at: "2026-11-05T09:31:00+08:00",
  updated_at: "2026-11-05T09:31:00+08:00",
  started_at: null,
  finished_at: null,
  current_stage: null,
  stats: { model_calls: 0, tokens_in: 0, tokens_out: 0, elapsed_ms: 0 },
  report_id: null,
  error: null,
  config_digest: "hash",
  graph_version: "graph-v1",
  retry_of_job_id: null,
  resume_of_job_id: null,
  resume_from_stage: null,
  allowed_actions: ["cancel"],
  links: {
    self: "/api/v1/jobs/job-1",
    events: "/api/v1/jobs/job-1/events",
    report: null,
  },
  stages: [],
  reconcile_notes: [],
};

const SEARCH_ITEMS: MarketSearchData = {
  items: [
    { ticker_code: "300750", ticker_name: "宁德时代", market: "sz" },
    { ticker_code: "300751", ticker_name: "宁德时代B", market: "sz" },
  ],
  truncated: false,
};

function searchEnvelope(data: MarketSearchData): MarketEnvelope<MarketSearchData> {
  return {
    schema_version: "market-envelope-v1",
    status: "ok",
    source: "static",
    as_of: "2026-11-05T09:00:00+08:00",
    fetched_at: "2026-11-05T09:00:00+08:00",
    is_stale: false,
    stale_reason: null,
    error_code: null,
    error_message: null,
    partial: false,
    failed_blocks: [],
    data,
  };
}

function errorBody(
  code: string,
  message: string,
  details?: Record<string, unknown>,
) {
  return {
    error: {
      code,
      message,
      request_id: "req_test",
      ...(details === undefined ? {} : { details }),
    },
  };
}

const SELECTED: TickerSelection = { code: "300750", name: "宁德时代" };

const EXPECTED_BODY: CreateJobRequest = {
  ticker: "300750",
  analysis_date: "2026-11-05",
  config: {
    llm_profile: "deepseek-default",
    parallel_analysts: true,
    stage_toggles: { policy: true, hot_money: true, lockup: true },
  },
};

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}</output>;
}

interface HarnessOptions {
  initialTicker?: TickerSelection | null;
  initialDate?: string | null;
}

function renderLauncher(options: HarnessOptions = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const created: JobDetail[] = [];

  function Harness() {
    const [open, setOpen] = useState(true);
    const navigate = useNavigate();
    if (!open) {
      return <p>启动器已关闭</p>;
    }
    return (
      <LauncherDialog
        open
        initialTicker={options.initialTicker ?? null}
        initialDate={options.initialDate ?? null}
        onClose={() => setOpen(false)}
        onCreated={(job) => {
          created.push(job);
          navigate(`/jobs/${job.job_id}`, { replace: true });
        }}
      />
    );
  }

  const router = createMemoryRouter(
    [
      { path: "/workbench", element: <Harness /> },
      { path: "/jobs/:jobId", element: <LocationProbe /> },
    ],
    { initialEntries: ["/workbench"] },
  );

  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );

  return { client, created, router };
}

async function submitButton() {
  const button = await screen.findByRole("button", { name: /开始分析|提交中|正在打开/ });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}

beforeEach(() => {
  server.use(
    http.get(META_URL, () => HttpResponse.json(META)),
    http.get(SEARCH_URL, () => HttpResponse.json(searchEnvelope(SEARCH_ITEMS))),
  );
});

describe("WEB-09 launcher form", () => {
  it("prefills the ticker, server default date and server config enums", async () => {
    const state = { posts: 0 };
    server.use(
      http.post(JOBS_URL, () => {
        state.posts += 1;
        return HttpResponse.json(JOB, { status: 201 });
      }),
    );
    renderLauncher({ initialTicker: SELECTED });

    expect(
      await screen.findByRole("dialog", { name: "分析启动器" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("宁德时代")).toBeInTheDocument();
    expect(screen.getByText("300750")).toBeInTheDocument();

    const date = (await screen.findByLabelText("分析日期")) as HTMLInputElement;
    await waitFor(() => expect(date.value).toBe("2026-11-05"));
    expect(date.max).toBe("2026-11-05");

    const profile = screen.getByLabelText("模型配置") as HTMLSelectElement;
    expect(profile.value).toBe("deepseek-default");
    expect(
      within(profile).getByRole("option", { name: "通义千问 Max" }),
    ).toBeInTheDocument();

    expect(screen.queryByRole("checkbox", { name: "政策分析" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /阶段开关/ }));
    expect(
      await screen.findByRole("checkbox", { name: "政策分析" }),
    ).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "解禁分析" })).toBeChecked();

    expect(screen.getByText(/分析会调用付费模型，预计 5–15 分钟/)).toBeInTheDocument();
    expect(screen.getByText(/取消只关闭表单/)).toBeInTheDocument();
    expect(state.posts).toBe(0);
  });

  it("searches by name, waits for a pick and never submits while editing", async () => {
    const state = { posts: 0 };
    server.use(
      http.post(JOBS_URL, () => {
        state.posts += 1;
        return HttpResponse.json(JOB, { status: 201 });
      }),
    );
    renderLauncher();

    const input = await screen.findByLabelText("搜索股票代码或名称");
    fireEvent.change(input, { target: { value: "宁德" } });
    const listbox = await screen.findByRole("listbox", { name: "搜索结果" });
    const options = await within(listbox).findAllByRole("option");
    fireEvent.mouseDown(options[0]);

    expect(await screen.findByText("宁德时代")).toBeInTheDocument();
    expect(screen.getByText("300750")).toBeInTheDocument();
    expect(state.posts).toBe(0);
  });

  it("sends the exact contract body with one idempotency key and jumps on 201", async () => {
    const seen: { body: unknown; key: string | null }[] = [];
    server.use(
      http.post(JOBS_URL, async ({ request }) => {
        seen.push({
          body: await request.json(),
          key: request.headers.get("Idempotency-Key"),
        });
        return HttpResponse.json(JOB, { status: 201 });
      }),
    );
    const { client, router } = renderLauncher({ initialTicker: SELECTED });
    client.setQueryData(["jobs", { limit: 3 }], { items: [], next_cursor: null });

    fireEvent.click(await submitButton());
    await waitFor(() => expect(seen).toHaveLength(1));

    expect(seen[0].body).toEqual(EXPECTED_BODY);
    expect(typeof seen[0].key).toBe("string");
    expect(seen[0].key).not.toBe("");

    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/jobs/job-1"),
    );
    expect(
      client.getQueryState(["jobs", { limit: 3 }])?.isInvalidated,
    ).toBe(true);
  });

  it("disables the button on the first click and a burst sends one POST", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let posts = 0;
    server.use(
      http.post(JOBS_URL, async () => {
        posts += 1;
        await gate;
        return HttpResponse.json(JOB, { status: 201 });
      }),
    );
    const { router } = renderLauncher({ initialTicker: SELECTED });

    const button = await submitButton();
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);

    const pending = await screen.findByRole("button", { name: "提交中" });
    expect(pending).toBeDisabled();
    expect(posts).toBe(1);

    await act(async () => {
      release();
    });
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/jobs/job-1"),
    );
    expect(posts).toBe(1);
  });

  it("opens the existing job and says so on 200 + X-Existing-Job", async () => {
    server.use(
      http.post(JOBS_URL, () =>
        HttpResponse.json(JOB, {
          status: 200,
          headers: { "X-Existing-Job": "job-1" },
        }),
      ),
    );
    const { router } = renderLauncher({ initialTicker: SELECTED });

    fireEvent.click(await submitButton());

    expect(await screen.findByText("已有一个相同分析")).toBeInTheDocument();
    await waitFor(
      () => expect(router.state.location.pathname).toBe("/jobs/job-1"),
      { timeout: 3000 },
    );
  });

  it("keeps a 409 conflict in the form with a link to the active job", async () => {
    let posts = 0;
    server.use(
      http.post(JOBS_URL, () => {
        posts += 1;
        return HttpResponse.json(
          errorBody("active_conflict", "该股票今日已有进行中的分析", {
            active_job_id: "job-9",
          }),
          { status: 409 },
        );
      }),
    );
    renderLauncher({ initialTicker: SELECTED });

    fireEvent.click(await submitButton());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("该股票今日已有进行中的分析");
    expect(
      within(alert).getByRole("link", { name: "查看进行中的任务" }),
    ).toHaveAttribute("href", "/jobs/job-9");

    fireEvent.click(within(alert).getByRole("button", { name: "取消" }));

    await waitFor(() =>
      expect(
        screen.queryByText("该股票今日已有进行中的分析"),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByText("宁德时代")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "开始分析" }),
    ).toBeEnabled();
    expect(posts).toBe(1);
  });

  it("shows ambiguous candidates and lets the user pick one", async () => {
    server.use(
      http.post(JOBS_URL, () =>
        HttpResponse.json(
          errorBody("ticker_ambiguous", "匹配到多只股票，请选择一只", {
            candidates: [
              { code: "300750", name: "宁德时代A" },
              { code: "300751", name: "宁德时代B" },
            ],
          }),
          { status: 422 },
        ),
      ),
    );
    renderLauncher();

    const input = await screen.findByLabelText("搜索股票代码或名称");
    fireEvent.change(input, { target: { value: "300750" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await screen.findByText("300750");

    fireEvent.click(await submitButton());

    expect(
      await screen.findByText("匹配到多只股票，请选择一只"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /宁德时代B/ }));
    await waitFor(() =>
      expect(screen.getAllByText("300751").length).toBeGreaterThan(0),
    );
  });

  it("keeps the date and shows an invalid_date error on the field", async () => {
    server.use(
      http.post(JOBS_URL, () =>
        HttpResponse.json(
          errorBody("invalid_date", "分析日期不正确", { field: "analysis_date" }),
          { status: 422 },
        ),
      ),
    );
    renderLauncher({ initialTicker: SELECTED });

    fireEvent.click(await submitButton());

    expect(await screen.findByText("分析日期不正确")).toBeInTheDocument();
    const date = screen.getByLabelText("分析日期") as HTMLInputElement;
    expect(date.value).toBe("2026-11-05");
    expect(screen.getByText("300750")).toBeInTheDocument();
  });

  it("keeps the config error on the profile field and lists allowed values", async () => {
    server.use(
      http.post(JOBS_URL, () =>
        HttpResponse.json(
          errorBody("config_invalid_value", "配置取值不支持", {
            field: "llm_profile",
            allowed_values: ["deepseek-default", "qwen-max"],
          }),
          { status: 422 },
        ),
      ),
    );
    renderLauncher({ initialTicker: SELECTED });

    fireEvent.click(await submitButton());

    expect(await screen.findByText(/配置取值不支持/)).toBeInTheDocument();
    expect(
      screen.getByText(/允许值：deepseek-default、qwen-max/),
    ).toBeInTheDocument();
    const profile = screen.getByLabelText("模型配置") as HTMLSelectElement;
    expect(profile.value).toBe("deepseek-default");
  });

  it("counts down a 429 and blocks submit until it ends", async () => {
    let posts = 0;
    server.use(
      http.post(JOBS_URL, () => {
        posts += 1;
        return HttpResponse.json(
          errorBody("rate_limited", "操作太频繁，请稍后再试", {
            retry_after_ms: 1000,
          }),
          { status: 429 },
        );
      }),
    );
    renderLauncher({ initialTicker: SELECTED });

    fireEvent.click(await submitButton());

    expect(
      await screen.findByText(/请等待 1 秒/),
    ).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "开始分析" });
    expect(button).toBeDisabled();

    await waitFor(() => expect(button).toBeEnabled(), { timeout: 4000 });
    expect(posts).toBe(1);
  });

  it("reuses the key after a network failure and changes it after an edit", async () => {
    const keys: (string | null)[] = [];
    server.use(
      http.post(JOBS_URL, ({ request }) => {
        keys.push(request.headers.get("Idempotency-Key"));
        return HttpResponse.error();
      }),
    );
    renderLauncher({ initialTicker: SELECTED });

    fireEvent.click(await submitButton());
    await screen.findByText("网络连接失败，请检查网络后重试");

    fireEvent.click(await submitButton());
    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[1]).toBe(keys[0]);

    fireEvent.change(screen.getByLabelText("分析日期"), {
      target: { value: "2026-11-04" },
    });
    fireEvent.click(await submitButton());
    await waitFor(() => expect(keys).toHaveLength(3));
    expect(keys[2]).not.toBe(keys[0]);
  });

  it("never posts when the launcher is opened and closed", async () => {
    let posts = 0;
    server.use(
      http.post(JOBS_URL, () => {
        posts += 1;
        return HttpResponse.json(JOB, { status: 201 });
      }),
    );
    renderLauncher();

    await screen.findByRole("dialog", { name: "分析启动器" });
    fireEvent.click(screen.getByRole("button", { name: "取消" }));

    expect(await screen.findByText("启动器已关闭")).toBeInTheDocument();
    expect(posts).toBe(0);
  });

  it("shows a retry when meta/options fails and keeps submit disabled", async () => {
    server.use(
      http.get(META_URL, () =>
        HttpResponse.json(
          errorBody("internal_error", "服务暂时不可用"),
          { status: 500 },
        ),
      ),
    );
    renderLauncher({ initialTicker: SELECTED });

    expect(await screen.findByText("服务暂时不可用")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始分析" })).toBeDisabled();
  });

  it("prefills the analysis date requested by the caller", async () => {
    renderLauncher({
      initialTicker: SELECTED,
      initialDate: "2026-10-28",
    });

    const date = (await screen.findByLabelText("分析日期")) as HTMLInputElement;
    await waitFor(() => expect(date.value).toBe("2026-10-28"));
    expect(date.max).toBe("2026-11-05");
  });

  it("does not invent a price in the cost copy", async () => {
    renderLauncher({ initialTicker: SELECTED });
    await screen.findByRole("dialog", { name: "分析启动器" });
    expect(document.body.textContent).toContain(
      "分析会调用付费模型，预计 5–15 分钟",
    );
    expect(document.body.textContent).not.toMatch(/¥|\d+\s*元/);
  });

  // FE-WM-01 ------------------------------------------------------------

  it("blocks submit and explains why while the legacy UI is the writer", async () => {
    let posts = 0;
    server.use(
      http.get(META_URL, () =>
        HttpResponse.json({ ...META, write_mode: "legacy" }),
      ),
      http.post(JOBS_URL, () => {
        posts += 1;
        return HttpResponse.json(JOB, { status: 201 });
      }),
    );
    renderLauncher({ initialTicker: SELECTED });

    expect(await screen.findByTestId("launcher-write-mode")).toHaveTextContent(
      "当前由旧版发起分析，请到旧版入口开始分析",
    );
    expect(
      within(screen.getByTestId("launcher-write-mode")).getByRole("link", {
        name: "打开旧版界面",
      }),
    ).toHaveAttribute("href", "http://localhost:8501");
    expect(screen.getByRole("button", { name: "开始分析" })).toBeDisabled();
    expect(posts).toBe(0);
  });

  it("stays submittable when write_mode is next or absent", async () => {
    server.use(
      http.get(META_URL, () => HttpResponse.json({ ...META, write_mode: "next" })),
      http.post(JOBS_URL, () => HttpResponse.json(JOB, { status: 201 })),
    );
    renderLauncher({ initialTicker: SELECTED });

    await submitButton();
    expect(screen.queryByTestId("launcher-write-mode")).toBeNull();
  });

  // FE-WM-02 ------------------------------------------------------------

  it("shows the legacy-writer message when the server answers 409", async () => {
    server.use(
      http.post(JOBS_URL, () =>
        HttpResponse.json(
          errorBody(
            "write_mode_legacy",
            "当前由旧版发起分析，请到旧版入口开始分析",
          ),
          { status: 409 },
        ),
      ),
    );
    renderLauncher({ initialTicker: SELECTED });

    fireEvent.click(await submitButton());

    expect(
      await screen.findByText("当前由旧版发起分析，请到旧版入口开始分析"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始分析" })).toBeEnabled();
  });
});
