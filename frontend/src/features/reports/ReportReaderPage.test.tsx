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
  type MockInstance,
} from "vitest";

import type { ReportDetail, ReportMeta, ReportSection } from "../../api/types";
import { ReportReaderPage } from "./ReportReaderPage";

const ORIGIN = "http://localhost:3000";
const DETAIL_URL = `${ORIGIN}/api/v1/reports/:reportId`;

const server = setupServer();
beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
  // jsdom does not implement scrolling; the reader only needs the call.
  Element.prototype.scrollIntoView = () => {};
});
afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});
afterAll(() => {
  server.close();
  vi.unstubAllGlobals();
});

class FakeIntersectionObserver {
  static instances: FakeIntersectionObserver[] = [];
  readonly observed: Element[] = [];
  private readonly callback: IntersectionObserverCallback;

  constructor(
    callback: IntersectionObserverCallback,
    _options?: IntersectionObserverInit,
  ) {
    this.callback = callback;
    FakeIntersectionObserver.instances.push(this);
  }

  observe(target: Element): void {
    this.observed.push(target);
  }

  unobserve(): void {}

  disconnect(): void {}

  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }

  emit(sectionId: string, isIntersecting: boolean): void {
    const target = document.getElementById(sectionId);
    if (target === null) {
      throw new Error(`section ${sectionId} is not rendered`);
    }
    this.callback(
      [
        {
          target,
          isIntersecting,
        } as unknown as IntersectionObserverEntry,
      ],
      this as unknown as IntersectionObserver,
    );
  }
}

function meta(overrides: Partial<ReportMeta> = {}): ReportMeta {
  return {
    report_id: "r-1",
    job_id: "job-1",
    ticker_code: "600519",
    ticker_name: "贵州茅台",
    analysis_date: "2026-10-28",
    generated_at: "2026-10-28T11:41:00+08:00",
    generated_at_source: "job_clock",
    origin: "new",
    schema_version: "report-v1",
    content_hash: "hash-1",
    config_digest: "cfg-1",
    data_quality_status: "ok",
    chart_snapshot_status: "frozen",
    retry_of_job_id: null,
    rating: "Overweight",
    signal: "Buy",
    price_target: 1680.5,
    stop_reference: "1520",
    time_horizon: "3-6个月",
    ...overrides,
  };
}

function section(
  id: string,
  title: string,
  body: string,
  extra: Partial<ReportSection> = {},
): ReportSection {
  return { id, title, body, ...extra };
}

function detail({
  metaOverrides = {},
  sections,
}: {
  metaOverrides?: Partial<ReportMeta>;
  sections?: Record<string, ReportSection>;
} = {}): ReportDetail {
  return {
    meta: meta(metaOverrides),
    sections: sections ?? {
      // Insertion order deliberately disagrees with the contract order.
      "sec-risk": section("sec-risk", "风控评估", "风控正文"),
      "sec-market": section("sec-market", "技术分析", "技术正文"),
      "sec-decision": section("sec-decision", "最终交易决策", "决策正文"),
      "sec-policy": section("sec-policy", "政策分析", "   "),
    },
  };
}

let methods: string[] = [];
let paths: string[] = [];
let scrollSpy: MockInstance;

function serve(body: ReportDetail, status = 200): void {
  server.use(
    http.get(DETAIL_URL, ({ request }) => {
      methods.push(request.method);
      paths.push(new URL(request.url).pathname);
      return HttpResponse.json(body, { status });
    }),
  );
}

function renderPage(entry: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: "/reports", element: <div data-testid="page-reports-stub" /> },
      { path: "/reports/:reportId", element: <ReportReaderPage /> },
      { path: "/jobs/:jobId", element: <div data-testid="page-job-stub" /> },
    ],
    { initialEntries: [entry] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

function tocLink(sectionId: string): HTMLElement {
  const link = document.querySelector<HTMLElement>(
    `[data-testid="toc-link"][data-section-id="${sectionId}"]`,
  );
  if (link === null) {
    throw new Error(`missing toc link for ${sectionId}`);
  }
  return link;
}

beforeEach(() => {
  FakeIntersectionObserver.instances = [];
  methods = [];
  paths = [];
  document.getElementById("main-content")?.remove();
  const main = document.createElement("div");
  main.id = "main-content";
  document.body.append(main);
  scrollSpy = vi.spyOn(Element.prototype, "scrollIntoView");
});

describe("RDR-01 table of contents", () => {
  it("lists only present sections in contract order with chapter numbers", async () => {
    serve(detail());
    renderPage("/reports/r-1");

    const links = await screen.findAllByTestId("toc-link");
    expect(links.map((link) => link.dataset.sectionId)).toEqual([
      "sec-decision",
      "sec-market",
      "sec-risk",
    ]);
    expect(links[0]).toHaveTextContent("1");
    expect(links[0]).toHaveTextContent("最终交易决策");
    expect(links[2]).toHaveTextContent("13");
    expect(links[2]).toHaveTextContent("风控评估");

    const sections = screen.getAllByTestId("report-section");
    expect(sections.map((element) => element.id)).toEqual([
      "sec-decision",
      "sec-market",
      "sec-risk",
    ]);
  });
});

describe("RDR-02 scrolling, highlighting and hash", () => {
  it("highlights the section in view and jumps on click while syncing the hash", async () => {
    serve(detail());
    const router = renderPage("/reports/r-1");
    await screen.findByTestId("report-article");
    await waitFor(() =>
      expect(FakeIntersectionObserver.instances).toHaveLength(1),
    );
    const observer = FakeIntersectionObserver.instances[0];
    await waitFor(() =>
      expect(observer.observed.map((element) => element.id)).toEqual([
        "sec-decision",
        "sec-market",
        "sec-risk",
      ]),
    );

    act(() => observer.emit("sec-market", true));
    await waitFor(() =>
      expect(tocLink("sec-market")).toHaveAttribute("aria-current", "location"),
    );
    expect(tocLink("sec-decision")).not.toHaveAttribute("aria-current");

    fireEvent.click(tocLink("sec-risk"));
    await waitFor(() =>
      expect(router.state.location.hash).toBe("#sec-risk"),
    );
    await waitFor(() =>
      expect(tocLink("sec-risk")).toHaveAttribute("aria-current", "location"),
    );
    expect(scrollSpy).toHaveBeenCalledWith({ block: "start" });
  });
});

describe("RDR-03 deep links", () => {
  it("opens at #sec-debate-style anchors once the body is rendered", async () => {
    serve(detail());
    renderPage("/reports/r-1#sec-risk");
    await screen.findByTestId("report-article");

    await waitFor(() =>
      expect(scrollSpy.mock.instances).toContain(
        document.getElementById("sec-risk"),
      ),
    );
    await waitFor(() =>
      expect(tocLink("sec-risk")).toHaveAttribute("aria-current", "location"),
    );
  });

  it("stays at the top for a missing anchor without an error", async () => {
    serve(detail());
    renderPage("/reports/r-1#sec-missing");
    await screen.findByTestId("report-article");

    await waitFor(() =>
      expect(tocLink("sec-decision")).toHaveAttribute(
        "aria-current",
        "location",
      ),
    );
    expect(scrollSpy).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("RDR-04 missing decision fields", () => {
  it("shows an em dash and hides absent chapters", async () => {
    serve(
      detail({
        metaOverrides: {
          rating: "unknown",
          signal: "unknown",
          price_target: null,
          stop_reference: null,
          time_horizon: null,
        },
        sections: {
          "sec-decision": section("sec-decision", "最终交易决策", "决策正文"),
          "sec-market": section("sec-market", "技术分析", "技术正文"),
        },
      }),
    );
    renderPage("/reports/r-1");

    await screen.findByTestId("decision-card");
    expect(screen.getByTestId("decision-rating")).toHaveTextContent("未知");
    expect(screen.getByTestId("decision-signal")).toHaveTextContent("—");
    expect(screen.getByTestId("decision-price-target")).toHaveTextContent("—");
    expect(screen.getByTestId("decision-stop")).toHaveTextContent("—");
    expect(screen.getByTestId("decision-horizon")).toHaveTextContent("—");
    expect(screen.getAllByTestId("toc-link")).toHaveLength(2);
    expect(
      document.querySelector('[data-section-id="sec-sentiment"]'),
    ).toBeNull();
  });
});

describe("RDR-05 meta panel", () => {
  it("shows DTO time, origin, quality and the source job", async () => {
    serve(detail());
    renderPage("/reports/r-1");

    expect(await screen.findByTestId("meta-generated-at")).toHaveTextContent(
      "10-28 11:41",
    );
    expect(screen.getByTestId("meta-origin")).toHaveTextContent("AI 分析");
    expect(screen.getByTestId("meta-data-quality")).toHaveTextContent("正常");
    expect(screen.getByTestId("meta-job")).toHaveAttribute(
      "href",
      "/jobs/job-1",
    );
  });

  it("marks a legacy import unknown and omits the job link", async () => {
    serve(
      detail({
        metaOverrides: {
          job_id: null,
          origin: "legacy_import",
          generated_at: null,
          generated_at_source: "unknown",
          data_quality_status: "absent",
          chart_snapshot_status: "none",
        },
      }),
    );
    renderPage("/reports/r-1");

    expect(await screen.findByTestId("meta-generated-at")).toHaveTextContent(
      "生成时间未知",
    );
    expect(screen.getByTestId("meta-origin")).toHaveTextContent("历史导入");
    expect(screen.getByTestId("meta-data-quality")).toHaveTextContent("缺失");
    expect(screen.queryByTestId("meta-job")).toBeNull();
  });
});

describe("RDR-06 safe markdown", () => {
  it("drops raw HTML and javascript: links, and opens external links safely", async () => {
    serve(
      detail({
        sections: {
          "sec-news": section(
            "sec-news",
            "新闻舆情",
            [
              '## 注入样本 <script>alert("xss")</script>',
              "<img src=x onerror=alert(1)>",
              "![图](data:text/html;base64,PHNjcmlwdD4=)",
              "[伪装链接](javascript:alert(1))",
              "[外链](https://example.com/report)",
              "| 指标 | 值 |\n| --- | --- |\n| 样本行 | 1 |",
            ].join("\n\n"),
          ),
        },
      }),
    );
    renderPage("/reports/r-1");

    const article = await screen.findByTestId("report-article");
    expect(article.querySelector("script")).toBeNull();
    expect(article.querySelector("img")).toBeNull();
    expect(article.innerHTML).not.toMatch(/onerror/i);
    expect(article.innerHTML).not.toMatch(/javascript:/i);

    const external = within(article).getByRole("link", { name: "外链" });
    expect(external).toHaveAttribute("target", "_blank");
    expect(external).toHaveAttribute("rel", "noopener noreferrer");

    const table = article.querySelector("table");
    expect(table).not.toBeNull();
    expect(table).toHaveTextContent("样本行");
  });
});

describe("RDR-07 long reports", () => {
  it("renders every paragraph through the tail", async () => {
    const paragraphs = Array.from(
      { length: 250 },
      (_, index) => `正文第 ${index + 1} 段，用于不截断验证。`,
    );
    const tail = "尾部标记-NOT-TRUNCATED";
    serve(
      detail({
        sections: {
          "sec-decision": section(
            "sec-decision",
            "最终交易决策",
            `${paragraphs.join("\n\n")}\n\n${tail}`,
          ),
        },
      }),
    );
    renderPage("/reports/r-1");

    expect(await screen.findByText(tail)).toBeInTheDocument();
    const article = screen.getByTestId("report-article");
    expect(article.textContent).toContain("正文第 250 段");
  });
});

describe("RDR-08 read-only opening", () => {
  it("sends exactly one detail GET and no other API request", async () => {
    serve(detail());
    renderPage("/reports/r-1");
    await screen.findByTestId("report-article");

    await waitFor(() => expect(paths).toHaveLength(1));
    expect(methods).toEqual(["GET"]);
    expect(paths).toEqual(["/api/v1/reports/r-1"]);
  });
});

describe("reader states", () => {
  it("shows the not-found state for report_not_found", async () => {
    serve(
      { error: { code: "report_not_found", message: "没有找到这份报告" } } as
        unknown as ReportDetail,
      404,
    );
    renderPage("/reports/missing");

    expect(await screen.findByTestId("reader-not-found")).toBeInTheDocument();
    expect(screen.getByText("没有找到这份报告")).toBeInTheDocument();
  });

  it("shows a safe error and refetches on retry", async () => {
    let failing = true;
    server.use(
      http.get(DETAIL_URL, () =>
        failing
          ? HttpResponse.json(
              { error: { code: "internal_error", message: "服务暂时不可用" } },
              { status: 500 },
            )
          : HttpResponse.json(detail()),
      ),
    );
    renderPage("/reports/r-1");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("服务暂时不可用");
    failing = false;
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByTestId("report-article")).toBeInTheDocument();
  });
});
