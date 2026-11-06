import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  blockLabel,
  SESSION_LABELS,
  sessionLabel,
  SOURCE_LABELS,
  sourceLabel,
  STALE_REASON_COPY,
  staleDescription,
} from "../features/market/copy";
import type { StaleReason } from "../api/types";
import { DataState } from "./DataState";

describe("DS-01 五态渲染与文案 / testid 差异", () => {
  it("loading 只显示骨架，不显示文案或重试", () => {
    render(
      <DataState state="loading">
        <p>内容</p>
      </DataState>,
    );

    expect(screen.getByTestId("data-state-loading")).toHaveAttribute(
      "data-state",
      "loading",
    );
    expect(screen.queryByText("内容")).not.toBeInTheDocument();
    expect(screen.queryByText("暂无数据")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("ok 显示内容且没有修饰", () => {
    render(
      <DataState state="ok">
        <p>内容</p>
      </DataState>,
    );

    const root = screen.getByTestId("data-state-ok");
    expect(root).toHaveAttribute("data-state", "ok");
    expect(root).toHaveAttribute("data-partial", "false");
    expect(screen.getByText("内容")).toBeInTheDocument();
  });

  it("empty 与 error 的文案和 testid 都不同", () => {
    const { rerender } = render(<DataState state="empty" />);
    expect(screen.getByTestId("data-state-empty")).toBeInTheDocument();
    expect(screen.getByText("暂无数据")).toBeInTheDocument();
    expect(screen.queryByText("数据源请求失败")).not.toBeInTheDocument();

    rerender(<DataState state="error" />);
    expect(screen.getByTestId("data-state-error")).toBeInTheDocument();
    expect(screen.getByText("数据源请求失败")).toBeInTheDocument();
    expect(screen.queryByText("暂无数据")).not.toBeInTheDocument();
  });

  it("empty 可覆盖为场景文案", () => {
    render(
      <DataState state="empty" emptyTitle="非交易日或盘后未更新" />,
    );

    expect(screen.getByText("非交易日或盘后未更新")).toBeInTheDocument();
  });
});

describe("DS-02 partial 修饰与块名", () => {
  it("可用内容照常显示，并列出失败块", () => {
    render(
      <DataState
        state="ok"
        partial
        failedBlocks={["quote", "valuation"]}
      >
        <p>可用内容</p>
      </DataState>,
    );

    expect(screen.getByTestId("data-state-ok")).toHaveAttribute(
      "data-partial",
      "true",
    );
    expect(screen.getByTestId("partial-notice")).toBeInTheDocument();
    expect(screen.getByText("部分数据不可用")).toBeInTheDocument();
    expect(screen.getByTestId("partial-blocks")).toHaveTextContent(
      "行情、估值",
    );
    expect(screen.getByText("可用内容")).toBeInTheDocument();
  });

  it("stale 加 partial 时两个修饰都渲染", () => {
    render(
      <DataState
        state="stale"
        staleReason="ttl_exceeded"
        partial
        failedBlocks={["northbound"]}
      />,
    );

    expect(screen.getByTestId("data-state-stale")).toHaveAttribute(
      "data-partial",
      "true",
    );
    expect(screen.getByTestId("stale-banner")).toBeInTheDocument();
    expect(screen.getByTestId("partial-notice")).toBeInTheDocument();
  });
});

describe("DS-03 stale 三种 reason 的文案", () => {
  it.each<[StaleReason, string]>([
    ["ttl_exceeded", "超过新鲜度阈值"],
    ["trading_day_mismatch", "数据日期早于最近交易日"],
    ["upstream_fallback", "已使用备用数据源"],
  ])("%s → %s", (reason, detail) => {
    render(<DataState state="stale" staleReason={reason} />);

    const banner = screen.getByTestId("stale-banner");
    expect(banner).toHaveTextContent("数据可能已过期");
    expect(banner).toHaveTextContent(detail);
  });

  it("未知 reason 只显示标题", () => {
    render(<DataState state="stale" staleReason={null} />);

    expect(screen.getByTestId("stale-banner")).toHaveTextContent(
      "数据可能已过期",
    );
    expect(screen.getByTestId("stale-banner").textContent).toBe(
      "数据可能已过期",
    );
  });
});

describe("DS-04 骨架与内容高度一致", () => {
  it("loading 高度与最终内容最小高度差不超过 8px", () => {
    const { rerender } = render(<DataState state="loading" skeletonHeight="320px" />);
    const skeletonHeight = Number.parseFloat(
      (screen.getByTestId("data-state-loading") as HTMLElement).style.height,
    );

    rerender(<DataState state="ok" skeletonHeight="320px" />);
    const contentHeight = Number.parseFloat(
      (screen.getByTestId("data-state-ok") as HTMLElement).style.minHeight,
    );

    expect(Math.abs(contentHeight - skeletonHeight)).toBeLessThanOrEqual(8);
  });
});

describe("DS-05 error 重试", () => {
  it("一次点击只回调一次", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<DataState state="error" onRetry={onRetry} />);

    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("未提供 retry 时不渲染按钮", () => {
    render(<DataState state="error" />);

    expect(
      screen.queryByRole("button", { name: "重试" }),
    ).not.toBeInTheDocument();
  });
});

describe("DS-06 无障碍语义", () => {
  it("loading aria-busy、error role=alert、stale role=status", () => {
    const { rerender } = render(<DataState state="loading" />);
    expect(screen.getByTestId("data-state-loading")).toHaveAttribute(
      "aria-busy",
      "true",
    );

    rerender(<DataState state="error" />);
    expect(screen.getByRole("alert")).toHaveTextContent("数据源请求失败");

    rerender(<DataState state="stale" staleReason="upstream_fallback" />);
    expect(screen.getByRole("status")).toHaveTextContent("已使用备用数据源");
  });
});

describe("copy 单一来源", () => {
  it("来源、会话、块名与 stale 原因都有中文映射", () => {
    expect(Object.keys(SOURCE_LABELS)).toEqual(
      expect.arrayContaining([
        "tencent",
        "eastmoney",
        "ths",
        "hexin",
        "cls",
        "mootdx",
        "mootdx-cache",
        "baidu",
        "mixed",
        "static",
      ]),
    );
    expect(sourceLabel("tencent")).toBe("腾讯");
    expect(sourceLabel("unknown-source")).toBe("unknown-source");

    expect(sessionLabel("pre_open")).toBe("未开盘");
    expect(sessionLabel("trading")).toBe("交易中");
    expect(sessionLabel("lunch_break")).toBe("午间休市");
    expect(sessionLabel("closed")).toBe("已收盘");
    expect(Object.keys(SESSION_LABELS)).toHaveLength(4);

    expect(blockLabel("quote")).toBe("行情");
    expect(blockLabel("valuation")).toBe("估值");
    expect(blockLabel("sector_blocks")).toBe("板块");
    expect(blockLabel("indices")).toBe("指数");
    expect(blockLabel("northbound")).toBe("北向");
    expect(blockLabel("mystery")).toBe("mystery");

    expect(Object.keys(STALE_REASON_COPY)).toHaveLength(3);
    expect(staleDescription(null)).toBeNull();
  });
});
