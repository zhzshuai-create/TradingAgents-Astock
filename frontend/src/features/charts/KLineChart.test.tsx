import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  DAILY_BARS,
  DAILY_DATA,
  MISSING_AMOUNT_DATA,
  WEEKLY_DATA,
} from "../../test/fixtures/charts";
import { KLineChart } from "./KLineChart";

function priceTicks(container: HTMLElement) {
  return [...container.querySelectorAll('[data-role="price-tick"]')];
}

function volumeBars(container: HTMLElement) {
  return [
    ...container.querySelectorAll('[data-role="volume-bar"]'),
  ] as SVGRectElement[];
}

function readWindow() {
  const node = screen.getByTestId("kline-window");
  return {
    start: Number(node.getAttribute("data-start")),
    end: Number(node.getAttribute("data-end")),
    count: Number(node.getAttribute("data-count")),
  };
}

function drag(
  hit: Element,
  fromX: number,
  toX: number,
): void {
  fireEvent.pointerDown(hit, {
    clientX: fromX,
    pointerId: 1,
    pointerType: "mouse",
  });
  fireEvent.pointerMove(hit, {
    clientX: toX,
    pointerId: 1,
    pointerType: "mouse",
  });
  fireEvent.pointerUp(hit, {
    clientX: toX,
    pointerId: 1,
    pointerType: "mouse",
  });
}

describe("CHT-01 价格轴与成交量副图", () => {
  it("刻度从上到下递增，成交量按最大值等比", () => {
    const { container } = render(
      <KLineChart data={DAILY_DATA} period="day" />,
    );

    const ticks = priceTicks(container);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    const values = ticks.map((node) => Number(node.getAttribute("data-value")));
    expect(values).toEqual([...values].sort((left, right) => left - right));
    const ys = ticks.map((node) =>
      Number(node.querySelector("line")?.getAttribute("y1")),
    );
    // Price grows upward, so larger tick values sit at smaller y.
    expect(ys).toEqual([...ys].sort((left, right) => right - left));

    const bars = volumeBars(container);
    expect(bars).toHaveLength(DAILY_BARS.length);
    const maxVolume = Math.max(...DAILY_BARS.map((item) => item.volume));
    expect(
      Math.max(...bars.map((node) => Number(node.dataset.height))),
    ).toBeCloseTo(56, 6);
    expect(Number(bars[0].dataset.height)).toBeCloseTo(
      (56 * DAILY_BARS[0].volume) / maxVolume,
      5,
    );

    const candles = container.querySelectorAll('[data-role="candle"]');
    expect(candles).toHaveLength(DAILY_BARS.length);
    expect(candles[0]).toHaveAttribute("data-direction", "up");
    expect(candles[1]).toHaveAttribute("data-direction", "down");
  });

  it("标注不复权与数据时间", () => {
    render(
      <KLineChart
        data={DAILY_DATA}
        period="day"
        asOf="2026-10-09T15:00:00+08:00"
      />,
    );

    const meta = screen.getByTestId("kline-meta");
    expect(meta).toHaveTextContent("不复权");
    expect(meta).toHaveTextContent("2026-10-09 15:00");
    expect(meta.querySelector("[data-adjust]")).toHaveAttribute(
      "data-adjust",
      "none",
    );
  });
});

describe("CHT-02 周期切换重算", () => {
  it("点击周期按钮回调，换数据后重算根数与标签", async () => {
    const user = userEvent.setup();
    const onPeriodChange = vi.fn();
    const { container, rerender } = render(
      <KLineChart
        data={DAILY_DATA}
        period="day"
        onPeriodChange={onPeriodChange}
      />,
    );

    await user.click(screen.getByTestId("kline-period-week"));
    expect(onPeriodChange).toHaveBeenCalledWith("week");

    rerender(
      <KLineChart
        data={WEEKLY_DATA}
        period="week"
        onPeriodChange={onPeriodChange}
      />,
    );

    expect(screen.getByTestId("kline-period-week")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByTestId("kline-period-day")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(container.querySelector('svg[data-chart="kline"]')).toHaveAttribute(
      "data-window-end",
      "8",
    );
    expect(container.querySelectorAll('[data-role="candle"]')).toHaveLength(8);
    expect(readWindow()).toEqual({ start: 0, end: 8, count: 8 });
  });
});

describe("CHT-03 缩放与平移", () => {
  it("滚轮缩小可见范围，最少 10 根", () => {
    render(<KLineChart data={DAILY_DATA} period="day" />);
    const svg = screen.getByRole("img", { name: /K 线/ });

    expect(readWindow().count).toBe(24);
    fireEvent.wheel(svg, { deltaY: -100, clientX: 300 });
    const zoomed = readWindow();
    expect(zoomed.count).toBeLessThan(24);
    expect(zoomed.count).toBeGreaterThanOrEqual(10);

    for (let index = 0; index < 8; index += 1) {
      fireEvent.wheel(svg, { deltaY: -100, clientX: 300 });
    }
    expect(readWindow().count).toBe(10);
  });

  it("拖拽平移在两端不越界", () => {
    const { container } = render(
      <KLineChart data={DAILY_DATA} period="day" />,
    );
    const svg = screen.getByRole("img", { name: /K 线/ });
    const hit = container.querySelector('[data-role="hit-area"]');
    expect(hit).not.toBeNull();
    if (hit === null) {
      return;
    }

    for (let index = 0; index < 8; index += 1) {
      fireEvent.wheel(svg, { deltaY: -100, clientX: 300 });
    }
    const before = readWindow();
    expect(before.count).toBe(10);
    drag(hit, 300, 600);
    const earlier = readWindow();
    expect(earlier.start).toBeLessThan(before.start);
    expect(earlier.start).toBeGreaterThanOrEqual(0);
    expect(earlier.end).toBeLessThanOrEqual(24);

    drag(hit, 600, 0);
    drag(hit, 600, 0);
    drag(hit, 600, 0);
    expect(readWindow()).toEqual({ start: 14, end: 24, count: 10 });
  });
});

describe("CHT-04 十字光标读数", () => {
  it("移动吸附到 K 线并显示日期，离开后回到最后一根", () => {
    const { container } = render(
      <KLineChart data={DAILY_DATA} period="day" />,
    );
    const hit = container.querySelector('[data-role="hit-area"]');
    expect(hit).not.toBeNull();
    if (hit === null) {
      return;
    }

    fireEvent.pointerMove(hit, { clientX: 105, pointerId: 1 });
    const readout = screen.getByTestId("kline-readout");
    expect(readout).toHaveAttribute("data-index", "3");
    expect(readout).toHaveAttribute("data-snapped", "true");
    expect(readout).toHaveTextContent(DAILY_BARS[3].date);
    expect(
      container.querySelector('[data-role="crosshair"]'),
    ).toHaveAttribute("data-index", "3");
    expect(
      container.querySelector('[data-role="crosshair-h"]'),
    ).not.toBeNull();

    fireEvent.pointerLeave(hit);
    expect(screen.getByTestId("kline-readout")).toHaveAttribute(
      "data-snapped",
      "false",
    );
    expect(
      container.querySelector('[data-role="crosshair"]'),
    ).toBeNull();
  });
});

describe("CHT-05 图例开关", () => {
  it("分别隐藏蜡烛与成交量，再恢复", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <KLineChart data={DAILY_DATA} period="day" />,
    );

    await user.click(screen.getByTestId("kline-legend-volume"));
    expect(volumeBars(container)).toHaveLength(0);
    expect(container.querySelectorAll('[data-role="candle"]')).toHaveLength(
      DAILY_BARS.length,
    );
    expect(screen.getByTestId("kline-legend-volume")).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    await user.click(screen.getByTestId("kline-legend-candles"));
    expect(container.querySelectorAll('[data-role="candle"]')).toHaveLength(0);
    expect(volumeBars(container)).toHaveLength(0);

    await user.click(screen.getByTestId("kline-legend-candles"));
    expect(container.querySelectorAll('[data-role="candle"]')).toHaveLength(
      DAILY_BARS.length,
    );
    await user.click(screen.getByTestId("kline-legend-volume"));
    expect(volumeBars(container)).toHaveLength(DAILY_BARS.length);
  });
});

describe("CHT-07 空数据与缺 amount", () => {
  it("空 bars 显示空态，不画图", () => {
    render(
      <KLineChart
        data={{ ...DAILY_DATA, bars: [] }}
        period="day"
      />,
    );
    expect(screen.getByTestId("kline-empty")).toHaveTextContent("暂无 K 线数据");
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("单根 K 线不崩，也不产生 NaN 几何", () => {
    const { container } = render(
      <KLineChart
        data={{ ...DAILY_DATA, bars: [DAILY_BARS[0]] }}
        period="day"
      />,
    );
    expect(container.querySelectorAll('[data-role="candle"]')).toHaveLength(1);
    expect(container.innerHTML).not.toContain("NaN");
    expect(screen.getByTestId("kline-readout")).toHaveTextContent(
      DAILY_BARS[0].date,
    );
  });

  it("amount=null 显示为缺省，不用 0 冒充", () => {
    render(<KLineChart data={MISSING_AMOUNT_DATA} period="day" />);
    const text = screen.getByTestId("kline-readout").textContent ?? "";
    expect(text).toContain("额");
    expect(text).toContain("—");
  });
});

describe("CHT-08 容器内滚动", () => {
  it("图表容器横向滚动被限制在自身，SVG 有最小宽度", () => {
    render(<KLineChart data={DAILY_DATA} period="day" />);
    const scroll = screen.getByTestId("kline-scroll");
    expect(scroll).toHaveAttribute("data-scroll", "x");
    expect(scroll.style.overflowX).toBe("auto");
    expect(scroll.style.minWidth).toBe("0px");
    expect(scroll.style.maxWidth).toBe("100%");
    expect(screen.getByRole("img", { name: /K 线/ }).style.minWidth).toBe(
      "640px",
    );
  });
});

describe("P5-07 chart text alternative", () => {
  it("SR-05 names the visible window and repeats it as text", () => {
    render(<KLineChart data={DAILY_DATA} period="day" />);

    const svg = screen.getByRole("img", { name: /日K K 线/ });
    const label = svg.getAttribute("aria-label") ?? "";
    expect(label).toContain("2026-09-01 至 2026-10-09");
    expect(label).toContain("共 24 根");
    expect(label).toContain("最新收盘 10.60 元");
    expect(label).toContain("-2.03%");

    const summary = screen.getByTestId("kline-summary");
    expect(summary).toHaveTextContent("2026-09-01 至 2026-10-09");
    expect(summary).toHaveTextContent("共 24 根");
    expect(summary).toHaveTextContent("最新收盘 10.60 元");
  });

  it("SR-05 explains the empty state instead of naming an empty image", () => {
    render(
      <KLineChart
        data={{ adjust: "none", bars: [], units: DAILY_DATA.units }}
        period="day"
      />,
    );
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.queryByTestId("kline-summary")).toBeNull();
    expect(screen.getByTestId("kline-empty")).toHaveTextContent("暂无 K 线数据");
  });
});
