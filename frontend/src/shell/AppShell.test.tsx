import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { routes } from "../routes";
import { SIDEBAR_STORAGE_KEY } from "./AppShell";
import { THEME_STORAGE_KEY } from "./useTheme";

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

const ROUTES = [
  ["/workbench", "page-workbench", "工作台"],
  ["/market", "page-market", "市场"],
  ["/stocks/600519", "page-stock", "600519 股票工作区"],
  ["/jobs", "page-jobs", "任务"],
  ["/jobs/job-1", "page-job-detail", "任务 job-1"],
  ["/reports", "page-reports", "报告"],
  ["/reports/report-1", "page-report-detail", "报告 report-1"],
  ["/journal", "page-journal", "交易日志"],
  ["/settings", "page-settings", "设置"],
] as const;

describe("WEB-03 routes", () => {
  it.each(ROUTES)("renders %s", (path, testId, heading) => {
    renderAt(path);
    const region = screen.getByTestId(testId);
    expect(within(region).getByRole("heading", { level: 1 })).toHaveTextContent(
      heading,
    );
  });

  it("redirects the root to the workbench", async () => {
    renderAt("/");
    expect(await screen.findByTestId("page-workbench")).toBeInTheDocument();
  });

  it("renders 404 with two working exits", () => {
    renderAt("/no-such-page");
    expect(screen.getByTestId("not-found")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "页面不存在" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "回工作台" })).toHaveAttribute(
      "href",
      "/workbench",
    );
    expect(screen.getByRole("link", { name: "回任务列表" })).toHaveAttribute(
      "href",
      "/jobs",
    );
  });

  it("does not auto redirect away from an unknown route", () => {
    const router = renderAt("/no-such-page");
    expect(router.state.location.pathname).toBe("/no-such-page");
  });
});

describe("WEB-03 active navigation", () => {
  it("marks the sidebar item for a job detail page", () => {
    renderAt("/jobs/job-1");
    const sidebar = screen.getByRole("complementary", { name: "主导航" });
    expect(within(sidebar).getByRole("link", { name: "任务" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      within(sidebar).getByRole("link", { name: "工作台" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("marks the sidebar item for a report detail page", () => {
    renderAt("/reports/report-1");
    const sidebar = screen.getByRole("complementary", { name: "主导航" });
    expect(within(sidebar).getByRole("link", { name: "报告" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("keeps the market item active inside a stock workspace", () => {
    renderAt("/stocks/600519");
    const sidebar = screen.getByRole("complementary", { name: "主导航" });
    expect(within(sidebar).getByRole("link", { name: "市场" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("marks the bottom navigation item", () => {
    renderAt("/reports/report-1");
    const mobileNav = screen.getByTestId("mobile-nav");
    const link = within(mobileNav).getByText("报告").closest("a");
    expect(link).toHaveAttribute("aria-current", "page");
    expect(
      within(mobileNav).getByText("工作台").closest("a"),
    ).not.toHaveAttribute("aria-current");
  });

  it("marks the more button for secondary routes", () => {
    renderAt("/journal");
    const mobileNav = screen.getByTestId("mobile-nav");
    const more = within(mobileNav).getByText("更多").closest("button");
    expect(more).toHaveAttribute("aria-current", "page");
  });
});

describe("WEB-03 invalid ticker", () => {
  it.each(["/stocks/abc", "/stocks/12345", "/stocks/60051a", "/stocks"])(
    "renders 400 for %s",
    (path) => {
      renderAt(path);
      const region = screen.getByTestId("invalid-ticker");
      expect(within(region).getByRole("heading", { level: 1 })).toHaveTextContent(
        "没有这只股票",
      );
      expect(within(region).getByLabelText("搜索股票")).toBeInTheDocument();
      expect(within(region).getByRole("link", { name: "回市场" })).toHaveAttribute(
        "href",
        "/market",
      );
    },
  );

  it("navigates to the stock workspace from the search box", async () => {
    renderAt("/workbench");
    fireEvent.change(screen.getByLabelText("搜索股票"), {
      target: { value: "600519" },
    });
    fireEvent.submit(screen.getByRole("search"));
    expect(await screen.findByTestId("page-stock")).toHaveTextContent(
      "600519 股票工作区",
    );
  });

  it("rejects a non six digit code in the search box", () => {
    renderAt("/workbench");
    fireEvent.change(screen.getByLabelText("搜索股票"), {
      target: { value: "茅台" },
    });
    fireEvent.submit(screen.getByRole("search"));
    expect(screen.getByRole("alert")).toHaveTextContent("请输入 6 位股票代码");
  });
});

describe("WEB-03 shell controls", () => {
  it("collapses and expands the sidebar, persisting the choice", () => {
    renderAt("/workbench");
    fireEvent.click(screen.getByRole("button", { name: "收起侧栏" }));
    expect(
      screen.getByRole("button", { name: "展开侧栏" }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "展开侧栏" }));
    expect(
      screen.getByRole("button", { name: "收起侧栏" }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("toggles the theme and persists it", () => {
    renderAt("/workbench");
    fireEvent.click(
      screen.getAllByRole("button", { name: "切换到深色主题" })[0],
    );
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(
      screen.getAllByRole("button", { name: "切换到浅色主题" }).length,
    ).toBeGreaterThan(0);
  });

  it("opens the more drawer with secondary navigation and legacy entry", () => {
    renderAt("/workbench");
    fireEvent.click(
      within(screen.getByTestId("mobile-nav")).getByText("更多").closest("button")!,
    );
    const drawer = screen.getByRole("dialog", { name: "更多" });
    expect(within(drawer).getByRole("link", { name: "交易日志" })).toHaveAttribute(
      "href",
      "/journal",
    );
    expect(within(drawer).getByRole("link", { name: "设置" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(within(drawer).getByRole("link", { name: "旧版入口" })).toHaveAttribute(
      "href",
      "http://localhost:8501",
    );
  });

  it("closes the more drawer after navigating", async () => {
    renderAt("/workbench");
    fireEvent.click(
      within(screen.getByTestId("mobile-nav")).getByText("更多").closest("button")!,
    );
    const drawer = screen.getByRole("dialog", { name: "更多" });
    fireEvent.click(within(drawer).getByRole("link", { name: "设置" }));
    expect(await screen.findByTestId("page-settings")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "更多" })).not.toBeInTheDocument();
    });
  });
});
