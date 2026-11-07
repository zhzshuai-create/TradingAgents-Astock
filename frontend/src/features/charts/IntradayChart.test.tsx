import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  INTRADAY_DATA,
  SINGLE_POINT_DATA,
} from "../../test/fixtures/charts";
import { IntradayChart } from "./IntradayChart";

function count(container: HTMLElement, role: string): number {
  return container.querySelectorAll(`[data-role="${role}"]`).length;
}

function linePointCounts(container: HTMLElement, role: string): number[] {
  return [
    ...container.querySelectorAll(`[data-role="${role}"]`),
  ].map((node) => (node.getAttribute("points") ?? "").trim().split(/\s+/).length);
}

describe("CHT-06 分时价格线、均价线与午休断线", () => {
  it("跨午休分成两段，均价线跳过 null 点", () => {
    const { container } = render(
      <IntradayChart
        data={INTRADAY_DATA}
        asOf="2026-11-05T15:00:00+08:00"
      />,
    );
    const svg = screen.getByRole("img", { name: /分时图/ });
    expect(svg).toHaveAttribute("data-segments", "2");
    expect(svg).toHaveAttribute("data-points", "12");

    expect(count(container, "price-line")).toBe(2);
    expect(count(container, "lunch-gap")).toBe(1);
    expect(count(container, "session-gap")).toBe(1);
    expect(count(container, "avg-line")).toBe(3);
    expect(
      linePointCounts(container, "avg-line").reduce(
        (sum, value) => sum + value,
        0,
      ),
    ).toBe(11);

    const price = [
      ...container.querySelectorAll('[data-role="price-line"]'),
    ];
    const firstPoints = (price[0].getAttribute("points") ?? "").split(" ");
    const secondPoints = (price[1].getAttribute("points") ?? "").split(" ");
    const lunchX = Number((10 + (120 / 330) * 654).toFixed(2));
    expect(
      Number(firstPoints[firstPoints.length - 1].split(",")[0]),
    ).toBeLessThanOrEqual(lunchX);
    expect(Number(secondPoints[0].split(",")[0])).toBeGreaterThanOrEqual(
      lunchX,
    );

    expect(screen.getByTestId("intraday-meta")).toHaveTextContent(
      "2026-11-05",
    );
    expect(screen.getByTestId("intraday-meta")).toHaveTextContent(
      "2026-11-05 15:00",
    );
  });

  it("时间轴四个标签覆盖上下午", () => {
    const { container } = render(<IntradayChart data={INTRADAY_DATA} />);
    const labels = [
      ...container.querySelectorAll('[data-role="time-label"]'),
    ].map((node) => node.textContent);
    expect(labels).toEqual(["09:30", "11:30", "13:00", "15:00"]);
  });
});

describe("CHT-04 分时十字光标吸附", () => {
  it("指针移动吸附到最近的分时点", () => {
    const { container } = render(<IntradayChart data={INTRADAY_DATA} />);
    const hit = container.querySelector('[data-role="hit-area"]');
    expect(hit).not.toBeNull();
    if (hit === null) {
      return;
    }

    fireEvent.pointerMove(hit, { clientX: 129, pointerId: 1 });
    const readout = screen.getByTestId("intraday-readout");
    expect(readout).toHaveAttribute("data-index", "3");
    expect(readout).toHaveAttribute("data-snapped", "true");
    expect(readout).toHaveTextContent("10:30");
    expect(
      container.querySelector('[data-role="crosshair"]'),
    ).toHaveAttribute("data-index", "3");

    fireEvent.pointerLeave(hit);
    expect(screen.getByTestId("intraday-readout")).toHaveAttribute(
      "data-snapped",
      "false",
    );
  });
});

describe("CHT-05 分时图例开关", () => {
  it("分别隐藏价格、均价与成交量", async () => {
    const user = userEvent.setup();
    const { container } = render(<IntradayChart data={INTRADAY_DATA} />);

    await user.click(screen.getByTestId("intraday-legend-avg"));
    expect(count(container, "avg-line")).toBe(0);
    expect(count(container, "price-line")).toBe(2);

    await user.click(screen.getByTestId("intraday-legend-price"));
    expect(count(container, "price-line")).toBe(0);

    await user.click(screen.getByTestId("intraday-legend-volume"));
    expect(count(container, "volume-bar")).toBe(0);

    await user.click(screen.getByTestId("intraday-legend-price"));
    expect(count(container, "price-line")).toBe(2);
  });
});

describe("CHT-07 分时空态与单点", () => {
  it("空 points 显示空态", () => {
    render(
      <IntradayChart data={{ ...INTRADAY_DATA, points: [] }} />,
    );
    expect(screen.getByTestId("intraday-empty")).toHaveTextContent(
      "暂无分时数据",
    );
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("单点画点不画线，且没有 NaN", () => {
    const { container } = render(
      <IntradayChart data={SINGLE_POINT_DATA} />,
    );
    expect(count(container, "price-dot")).toBe(1);
    expect(count(container, "price-line")).toBe(0);
    expect(count(container, "volume-bar")).toBe(1);
    expect(container.innerHTML).not.toContain("NaN");
    expect(screen.getByTestId("intraday-readout")).toHaveTextContent(
      "09:35",
    );
  });
});

describe("CHT-08 分时容器内滚动", () => {
  it("滚动限制在容器内，SVG 有最小宽度", () => {
    render(<IntradayChart data={INTRADAY_DATA} />);
    const scroll = screen.getByTestId("intraday-scroll");
    expect(scroll).toHaveAttribute("data-scroll", "x");
    expect(scroll.style.overflowX).toBe("auto");
    expect(scroll.style.minWidth).toBe("0px");
    expect(scroll.style.maxWidth).toBe("100%");
    expect(screen.getByRole("img", { name: /分时图/ }).style.minWidth).toBe(
      "640px",
    );
  });
});

describe("P5-07 chart text alternative", () => {
  it("SR-05 names the series with the facts already in the payload", () => {
    render(<IntradayChart data={INTRADAY_DATA} />);

    const svg = screen.getByRole("img", { name: /分时图/ });
    const label = svg.getAttribute("aria-label") ?? "";
    expect(label).toContain("共 12 个点");
    expect(label).toContain("最新 10.24 元");
    expect(label).toContain("最低 9.98 元");
    expect(label).toContain("最高 10.25 元");

    const summary = screen.getByTestId("intraday-summary");
    expect(summary).toHaveTextContent("09:30 至 15:00");
    expect(summary).toHaveTextContent("共 12 个点");
    expect(summary).toHaveTextContent("最新价 10.24 元");
  });

  it("SR-05 explains the empty state instead of naming an empty image", () => {
    render(
      <IntradayChart
        data={{ ...INTRADAY_DATA, points: [] }}
      />,
    );
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.queryByTestId("intraday-summary")).toBeNull();
    expect(screen.getByText("暂无分时数据")).toBeInTheDocument();
  });
});
