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
import { createMemoryRouter, RouterProvider } from "react-router-dom";
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

import { streamJobEvents } from "../../api/sse";
import type { MetaOptions } from "../../api/types";
import { PREFERENCES_STORAGE_KEY } from "../../lib/preferences";
import { queryKeys } from "../../lib/query";
import { SettingsView } from "./SettingsView";

const ORIGIN = "http://localhost:3000";
const META_URL = `${ORIGIN}/api/v1/meta/options`;
const EVENTS_URL = `${ORIGIN}/api/v1/jobs/job-1/events`;

const META: MetaOptions = {
  app_version: "0.9.0",
  server_time: "2026-11-05T09:30:00+08:00",
  default_analysis_date: "2026-11-05",
  llm_profiles: [
    { id: "deepseek-default", label: "DeepSeek 默认" },
    { id: "fast", label: "快速模型" },
  ],
  stage_toggles: [{ id: "policy", label: "政策分析", default: true }],
  limits: { max_active_jobs: 1, max_date_ahead_days: 0 },
  journal: {
    available: false,
    entry_url: "http://127.0.0.1:8502",
    reason: "not_running",
  },
  contract_version: "api-v1",
};

const server = setupServer();
const scrolledIds: string[] = [];
const scrollSpy = vi.fn(function (this: Element) {
  scrolledIds.push(this.id);
});

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  Element.prototype.scrollIntoView = scrollSpy;
});

afterEach(() => {
  server.resetHandlers();
  server.events.removeAllListeners();
  localStorage.clear();
  scrollSpy.mockClear();
  scrolledIds.length = 0;
});

afterAll(() => {
  server.close();
});

function serveMeta(overrides: Partial<MetaOptions> = {}): void {
  server.use(
    http.get(META_URL, () => HttpResponse.json({ ...META, ...overrides })),
  );
}

function renderSettings(initialEntry = "/settings") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter(
    [
      { path: "/settings", element: <SettingsView /> },
      { path: "/journal", element: <p>日志占位</p> },
      { path: "/jobs", element: <p>任务占位</p> },
      { path: "/market", element: <p>市场占位</p> },
    ],
    { initialEntries: [initialEntry] },
  );
  const result = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...result, router, client };
}

/** jsdom has no media queries; useIsMobile reads matchMedia on mount. */
function stubMobile(): () => void {
  const original = Object.getOwnPropertyDescriptor(window, "matchMedia");
  const list = {
    matches: true,
    media: "(max-width: 767px)",
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  };
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: () => list,
  });
  return () => {
    if (original === undefined) {
      delete (window as unknown as Record<string, unknown>).matchMedia;
    } else {
      Object.defineProperty(window, "matchMedia", original);
    }
  };
}

describe("SET desktop settings", () => {
  it("SET-01 renders the four groups with stable ids", async () => {
    serveMeta();
    const { container } = renderSettings();

    expect(
      await screen.findByRole("heading", { level: 1, name: "设置" }),
    ).toBeInTheDocument();
    const headings = await screen.findAllByRole("heading", { level: 2 });
    expect(headings.map((item) => item.textContent)).toEqual([
      "基本",
      "模型",
      "数据源",
      "关于",
    ]);
    expect(headings.map((item) => item.id)).toEqual([
      "group-basic",
      "group-model",
      "group-data",
      "group-about",
    ]);
    expect(
      container.querySelectorAll("section[aria-labelledby^='group-']"),
    ).toHaveLength(4);
  });

  it("SET-01 deep-links #group-model and scrolls to it on entry and remount", async () => {
    serveMeta();
    const first = renderSettings("/settings#group-model");

    expect(
      await screen.findByRole("heading", { level: 2, name: "模型" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(scrolledIds).toContain("group-model"));
    expect(first.router.state.location.hash).toBe("#group-model");
    first.unmount();

    // A remount with the same hash stands in for a page refresh.
    scrolledIds.length = 0;
    const second = renderSettings("/settings#group-model");
    await screen.findByRole("heading", { level: 2, name: "模型" });
    await waitFor(() => expect(scrolledIds).toContain("group-model"));
    expect(second.router.state.location.hash).toBe("#group-model");
  });

  it("LEG-02 links to the legacy entry from the about group", async () => {
    serveMeta();
    renderSettings();

    expect(await screen.findByText("接口可达")).toBeInTheDocument();
    const about = screen.getByRole("region", { name: "关于" });
    const link = within(about).getByRole("link", { name: "打开旧版界面" });

    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "http://localhost:8501");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    expect(screen.queryByText(/后续票据/)).toBeNull();
  });

  it("SET-02 renders read-only contract values from one cached query", async () => {
    let calls = 0;
    server.use(
      http.get(META_URL, () => {
        calls += 1;
        return HttpResponse.json(META);
      }),
    );
    const { client } = renderSettings();

    expect(await screen.findByText("接口可达")).toBeInTheDocument();
    expect(screen.getAllByText("0.9.0").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("api-v1")).toBeInTheDocument();
    expect(
      screen.getByText("2026-11-05T09:30:00+08:00"),
    ).toBeInTheDocument();
    expect(screen.getByText("http://127.0.0.1:8502")).toBeInTheDocument();
    expect(screen.getAllByText("DeepSeek 默认").length).toBeGreaterThan(0);
    expect(screen.getByText("deepseek-default")).toBeInTheDocument();

    expect(calls).toBe(1);
    expect(
      client.getQueryCache().find({ queryKey: queryKeys.metaOptions }),
    ).toBeDefined();
  });

  it("SET-03 shows the last SSE result and never invents health", async () => {
    serveMeta();
    renderSettings();

    expect(await screen.findByText("未连接")).toBeInTheDocument();

    server.use(
      http.get(
        EVENTS_URL,
        () =>
          new HttpResponse(": ping\n\n", {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          }),
      ),
    );
    await act(async () => {
      await streamJobEvents("job-1", {
        signal: new AbortController().signal,
        onEvent: () => {},
      });
    });
    expect(await screen.findByText("最近一次连接成功")).toBeInTheDocument();

    server.use(
      http.get(EVENTS_URL, () =>
        HttpResponse.json(
          { error: { code: "internal_error", message: "boom" } },
          { status: 500 },
        ),
      ),
    );
    await act(async () => {
      await streamJobEvents("job-1", {
        signal: new AbortController().signal,
        onEvent: () => {},
      }).catch(() => undefined);
    });
    expect(await screen.findByText("最近一次连接失败")).toBeInTheDocument();

    // Abort is covered at the module level in api/sse.test.ts: it must not
    // overwrite the recorded result.
  });

  it("SET-04 has no secret input and stores only the two preference keys", async () => {
    serveMeta();
    renderSettings();

    expect(await screen.findByText("接口可达")).toBeInTheDocument();
    expect(document.querySelector('input[type="password"]')).toBeNull();

    const fields = Array.from(
      document.querySelectorAll("input, textarea, select"),
    );
    for (const field of fields) {
      const identity = [
        field.getAttribute("id"),
        field.getAttribute("name"),
        field.getAttribute("type"),
      ]
        .join(" ")
        .toLowerCase();
      expect(identity).not.toMatch(/password|api_key|base_url|authorization/);
    }
    expect(document.body.textContent ?? "").not.toMatch(
      /sk-[A-Za-z0-9]|api_key|authorization/i,
    );

    fireEvent.change(screen.getByLabelText("列表密度"), {
      target: { value: "compact" },
    });
    expect(Object.keys(localStorage).sort()).toEqual([
      PREFERENCES_STORAGE_KEY,
    ]);
  });

  it("SET-05 saves preferences without any write request", async () => {
    serveMeta();
    const methods: string[] = [];
    const urls: string[] = [];
    server.events.on("request:start", ({ request }) => {
      methods.push(request.method);
      urls.push(request.url);
    });

    renderSettings();
    fireEvent.change(await screen.findByLabelText("列表密度"), {
      target: { value: "compact" },
    });
    fireEvent.change(screen.getByLabelText("默认模型"), {
      target: { value: "fast" },
    });
    fireEvent.click(screen.getByLabelText("默认并行分析师"));
    fireEvent.change(screen.getByLabelText("刷新频率"), {
      target: { value: "manual" },
    });
    fireEvent.change(screen.getByLabelText("导出顺序"), {
      target: { value: "markdown" },
    });

    expect(methods.length).toBeGreaterThan(0);
    expect(methods.every((method) => method === "GET")).toBe(true);
    expect(urls.some((url) => url.includes("/api/v1/jobs"))).toBe(false);
  });

  it("SET-06 announces every save and reads the value back after remount", async () => {
    serveMeta();
    const first = renderSettings();

    fireEvent.change(await screen.findByLabelText("列表密度"), {
      target: { value: "compact" },
    });
    expect(screen.getByRole("status")).toHaveTextContent("已保存");
    expect(
      JSON.parse(localStorage.getItem(PREFERENCES_STORAGE_KEY) ?? "{}"),
    ).toMatchObject({ density: "compact" });

    first.unmount();
    renderSettings();
    expect(await screen.findByLabelText("列表密度")).toHaveValue("compact");
    expect(screen.getByLabelText("默认并行分析师")).not.toBeChecked();
  });

  it("SET-07 ignores an unknown hash and stays at the top", async () => {
    serveMeta();
    const { router } = renderSettings("/settings#group-nope");

    await screen.findByRole("heading", { level: 1, name: "设置" });
    expect(router.state.location.hash).toBe("#group-nope");
    expect(scrolledIds).toEqual([]);
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(4);
  });

  it("SET-02 shows the server fallback without clearing a stale stored profile", async () => {
    serveMeta();
    localStorage.setItem(
      PREFERENCES_STORAGE_KEY,
      JSON.stringify({ launcher: { llm_profile: "removed-profile" } }),
    );
    renderSettings();

    expect(await screen.findByLabelText("默认模型")).toHaveValue("");
    expect(
      JSON.parse(localStorage.getItem(PREFERENCES_STORAGE_KEY) ?? "{}"),
    ).toMatchObject({ launcher: { llm_profile: "removed-profile" } });
  });
});

describe("SET mobile settings", () => {
  let restoreViewport: () => void = () => {};

  beforeEach(() => {
    restoreViewport = stubMobile();
  });

  afterEach(() => {
    restoreViewport();
  });

  it("SET-08 lists groups, drills into a detail page and clears the hash", async () => {
    serveMeta();
    const first = renderSettings();

    const nav = await screen.findByRole("navigation", { name: "设置分组" });
    expect(within(nav).getAllByRole("button")).toHaveLength(4);
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();

    fireEvent.click(within(nav).getByRole("button", { name: /模型/ }));
    await waitFor(() =>
      expect(first.router.state.location.hash).toBe("#group-model"),
    );
    expect(
      screen.getByRole("heading", { level: 2, name: "模型" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "设置分组" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "返回设置" }));
    await waitFor(() => expect(first.router.state.location.hash).toBe(""));
    expect(
      await screen.findByRole("navigation", { name: "设置分组" }),
    ).toBeInTheDocument();
    first.unmount();
  });

  it("SET-08 restores a deep-linked group and ignores an unknown one", async () => {
    serveMeta();
    const deep = renderSettings("/settings#group-data");
    expect(
      await screen.findByRole("heading", { level: 2, name: "数据源" }),
    ).toBeInTheDocument();
    expect(deep.router.state.location.hash).toBe("#group-data");
    deep.unmount();

    const invalid = renderSettings("/settings#group-nope");
    expect(
      await screen.findByRole("navigation", { name: "设置分组" }),
    ).toBeInTheDocument();
    expect(invalid.router.state.location.hash).toBe("#group-nope");
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
  });
});
