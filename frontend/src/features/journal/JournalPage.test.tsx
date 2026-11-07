import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getMetaOptions } from "../../api/meta";
import type { JournalReason, JournalStatus, MetaOptions } from "../../api/types";
import { JournalPage } from "../../pages/JournalPage";

vi.mock("../../api/meta", () => ({ getMetaOptions: vi.fn() }));

const getMetaMock = vi.mocked(getMetaOptions);

const ENTRY_URL = "http://127.0.0.1:8502";
const JOURNAL_ORIGIN = "http://127.0.0.1:8502";
const THEME_TYPE = "astock-theme-request";
const ISOLATION = "本系统不会读取或修改交易日志的数据。";

function meta(journal: JournalStatus): MetaOptions {
  return {
    app_version: "0.9.0",
    server_time: "2026-11-05T09:30:00+08:00",
    default_analysis_date: "2026-11-05",
    llm_profiles: [],
    stage_toggles: [],
    limits: { max_active_jobs: 1, max_date_ahead_days: 0 },
    journal,
    contract_version: "api-v1",
  };
}

function journal(reason: JournalReason | null): MetaOptions {
  return meta({ available: false, entry_url: ENTRY_URL, reason });
}

const AVAILABLE = meta({
  available: true,
  entry_url: ENTRY_URL,
  reason: null,
});

function renderJournal() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter(
    [{ path: "/journal", element: <JournalPage /> }],
    { initialEntries: ["/journal"] },
  );
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

async function mountUnavailable(reason: JournalReason | null) {
  getMetaMock.mockResolvedValue(journal(reason));
  const view = renderJournal();
  await screen.findByText("交易日志是独立应用，当前没有在运行。");
  return view;
}

beforeEach(() => {
  getMetaMock.mockReset();
  delete document.documentElement.dataset.theme;
});

afterEach(() => {
  vi.useRealTimers();
  delete document.documentElement.dataset.theme;
});

describe("JRN-01 available frame", () => {
  it("renders the running state, the iframe and a safe new-window link", async () => {
    getMetaMock.mockResolvedValue(AVAILABLE);
    renderJournal();

    expect(await screen.findByText("日志服务运行中")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "交易日志" })).toBeInTheDocument();

    const frame = screen.getByTitle("交易日志");
    expect(frame.tagName).toBe("IFRAME");
    expect(frame).toHaveAttribute("src", ENTRY_URL);

    const link = screen.getByRole("link", { name: "新窗口打开" });
    expect(link).toHaveAttribute("href", ENTRY_URL);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    expect(screen.getByRole("button", { name: "刷新" })).toBeInTheDocument();
  });

  it("refuses to embed an entry_url that is not http/https", async () => {
    getMetaMock.mockResolvedValue(
      meta({ available: true, entry_url: "file:///tmp/journal", reason: null }),
    );
    renderJournal();

    await screen.findByText("交易日志是独立应用，当前没有在运行。");
    expect(screen.queryByTitle("交易日志")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "新窗口打开" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("journal-isolation")).toHaveTextContent(ISOLATION);
  });
});

describe("JRN-02/JRN-03 reason copy", () => {
  it("not_running offers run.bat and the manual retry only", async () => {
    await mountUnavailable("not_running");

    expect(screen.getByText("trade-journal/run.bat")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "已启动，重试" })).toBeInTheDocument();
    expect(screen.queryByText(/安装/)).not.toBeInTheDocument();
    expect(screen.queryByText(/端口/)).not.toBeInTheDocument();
  });

  it("not_installed explains installation without a start command", async () => {
    await mountUnavailable("not_installed");

    expect(screen.getByText(/安装说明/)).toBeInTheDocument();
    expect(screen.queryByText(/run\.bat/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新检测" })).toBeInTheDocument();
  });

  it("probe_failed points at the port and proxy, not a start command", async () => {
    await mountUnavailable("probe_failed");

    expect(screen.getByText(/8502 端口/)).toBeInTheDocument();
    expect(screen.getByText(/代理/)).toBeInTheDocument();
    expect(screen.queryByText(/run\.bat/)).not.toBeInTheDocument();
  });

  it("treats a null reason as probe_failed without adding a state name", async () => {
    await mountUnavailable(null);

    expect(screen.getByText(/8502 端口/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新检测" })).toBeInTheDocument();
  });
});

describe("JRN-04 retry polling", () => {
  it("refetches every 2s and stops once the journal is available", async () => {
    await mountUnavailable("not_running");
    expect(getMetaMock).toHaveBeenCalledTimes(1);

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "已启动，重试" }));
    expect(screen.getByText("正在等待日志服务就绪…")).toBeInTheDocument();
    await act(async () => {});
    expect(getMetaMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_999);
    });
    expect(getMetaMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(getMetaMock).toHaveBeenCalledTimes(3);

    getMetaMock.mockResolvedValue(AVAILABLE);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(getMetaMock).toHaveBeenCalledTimes(4);
    expect(screen.getByText("日志服务运行中")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(getMetaMock).toHaveBeenCalledTimes(4);
  });

  it("shows the elapsed wait while the service is starting", async () => {
    await mountUnavailable("not_running");

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "已启动，重试" }));
    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });

    expect(screen.getByText(/已等待 3 秒/)).toBeInTheDocument();
  });

  it("stops polling when the user cancels", async () => {
    await mountUnavailable("not_running");

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "已启动，重试" }));
    await act(async () => {});
    const calls = getMetaMock.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "取消等待" }));
    expect(screen.getByText("交易日志是独立应用，当前没有在运行。")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(getMetaMock.mock.calls.length).toBe(calls);
  });
});

describe("JRN-05 retry timeout", () => {
  it("returns to unavailable after 30s and leaves no timer behind", async () => {
    const view = await mountUnavailable("probe_failed");

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "重新检测" }));
    await act(async () => {});

    await act(async () => {
      await vi.advanceTimersByTimeAsync(29_000);
    });
    expect(screen.getByText("正在等待日志服务就绪…")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(screen.queryByText("正在等待日志服务就绪…")).not.toBeInTheDocument();
    expect(screen.getByText("交易日志是独立应用，当前没有在运行。")).toBeInTheDocument();
    expect(screen.getByText(/8502 端口/)).toBeInTheDocument();

    const calls = getMetaMock.mock.calls.length;
    view.unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(getMetaMock.mock.calls.length).toBe(calls);
  });
});

describe("JRN-06/JRN-07 theme bridge", () => {
  function stubFrame() {
    const frame = screen.getByTitle("交易日志") as HTMLIFrameElement;
    const postMessage = vi.fn();
    const fakeWindow = { postMessage };
    Object.defineProperty(frame, "contentWindow", {
      configurable: true,
      value: fakeWindow,
    });
    return { frame, postMessage, fakeWindow };
  }

  function dispatch(data: unknown, origin: string, source: unknown) {
    const event = new MessageEvent("message", { data, origin });
    Object.defineProperty(event, "source", { configurable: true, value: source });
    act(() => {
      window.dispatchEvent(event);
    });
  }

  it("posts to the journal origin instead of '*'", async () => {
    getMetaMock.mockResolvedValue(AVAILABLE);
    renderJournal();
    await screen.findByText("日志服务运行中");

    const { frame, postMessage } = stubFrame();
    fireEvent.load(frame);

    expect(postMessage).toHaveBeenCalledWith(
      { type: THEME_TYPE, theme: "light" },
      JOURNAL_ORIGIN,
    );
    expect(postMessage.mock.calls[0][1]).not.toBe("*");
  });

  it("follows data-theme changes and carries the current theme", async () => {
    getMetaMock.mockResolvedValue(AVAILABLE);
    renderJournal();
    await screen.findByText("日志服务运行中");

    const { frame, postMessage } = stubFrame();
    fireEvent.load(frame);
    postMessage.mockClear();

    act(() => {
      document.documentElement.dataset.theme = "dark";
    });
    await waitFor(() =>
      expect(postMessage).toHaveBeenCalledWith(
        { type: THEME_TYPE, theme: "dark" },
        JOURNAL_ORIGIN,
      ),
    );

    postMessage.mockClear();
    fireEvent.load(frame);
    expect(postMessage).toHaveBeenCalledWith(
      { type: THEME_TYPE, theme: "dark" },
      JOURNAL_ORIGIN,
    );
  });

  it("ignores foreign origin, foreign window and foreign type", async () => {
    getMetaMock.mockResolvedValue(AVAILABLE);
    renderJournal();
    await screen.findByText("日志服务运行中");

    const { frame, postMessage, fakeWindow } = stubFrame();
    fireEvent.load(frame);
    postMessage.mockClear();

    dispatch({ type: THEME_TYPE, theme: "evil" }, "http://evil.example", fakeWindow);
    dispatch({ type: THEME_TYPE, theme: "evil" }, JOURNAL_ORIGIN, {
      postMessage: vi.fn(),
    });
    dispatch({ type: "other-message" }, JOURNAL_ORIGIN, fakeWindow);
    dispatch(null, JOURNAL_ORIGIN, fakeWindow);

    expect(postMessage).not.toHaveBeenCalled();

    dispatch({ type: THEME_TYPE, theme: "dark" }, JOURNAL_ORIGIN, fakeWindow);
    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledWith(
      { type: THEME_TYPE, theme: "light" },
      JOURNAL_ORIGIN,
    );
  });
});

describe("JRN-10 isolation statement", () => {
  it.each<JournalReason>(["not_running", "not_installed", "probe_failed"])(
    "keeps the data isolation line for %s",
    async (reason) => {
      await mountUnavailable(reason);
      expect(screen.getByTestId("journal-isolation")).toHaveTextContent(ISOLATION);
    },
  );

  it("reports a meta failure without guessing a journal reason", async () => {
    getMetaMock.mockRejectedValue(new Error("offline"));
    renderJournal();

    expect(
      await screen.findByText("暂时无法读取日志状态，请确认后端服务可用后重试。"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/run\.bat/)).not.toBeInTheDocument();
    expect(screen.getByTestId("journal-isolation")).toHaveTextContent(ISOLATION);
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });
});

describe("P5-07 journal status changes", () => {
  it("SR-04 announces the unavailable state once", async () => {
    await mountUnavailable("not_running");
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("交易日志是独立应用，当前没有在运行。");
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("SR-04 keeps retry progress in a single polite status", async () => {
    await mountUnavailable("not_running");
    fireEvent.click(screen.getByRole("button", { name: "已启动，重试" }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("正在等待日志服务");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
