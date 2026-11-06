import { describe, expect, it } from "vitest";

import {
  clockMinute,
  clampWindow,
  crossesSessionGap,
  extent,
  initialWindow,
  minuteToX,
  niceTicks,
  padDomain,
  panWindow,
  priceToY,
  sampleIndices,
  SESSION_MINUTES,
  slotWidth,
  volumeToHeight,
  xToMinute,
  zoomWindow,
} from "./chartScale";

const BOX = { left: 10, top: 0, width: 654, height: 100 };

describe("CHT-01 价格/成交量坐标映射", () => {
  it("extent 过滤非有限值，空输入返回 null", () => {
    expect(extent([3, Number.NaN, 1, 5])).toEqual({ min: 1, max: 5 });
    expect(extent([])).toBeNull();
  });

  it("平盘域被撑开，不塌成一条线", () => {
    expect(padDomain({ min: 10, max: 10 })).toEqual({ min: 9.5, max: 10.5 });
    expect(padDomain({ min: 10, max: 20 })).toEqual({ min: 9.4, max: 20.6 });
  });

  it("价格由高到低映射到 y 轴", () => {
    const domain = { min: 10, max: 20 };
    expect(priceToY(20, domain, BOX)).toBe(0);
    expect(priceToY(15, domain, BOX)).toBe(50);
    expect(priceToY(10, domain, BOX)).toBe(100);
    expect(priceToY(30, domain, BOX)).toBe(0);
    expect(priceToY(0, domain, BOX)).toBe(100);
  });

  it("成交量按最大量等比缩放", () => {
    expect(volumeToHeight(50, 100, 40)).toBe(20);
    expect(volumeToHeight(100, 100, 40)).toBe(40);
    expect(volumeToHeight(0, 100, 40)).toBe(0);
    expect(volumeToHeight(-5, 100, 40)).toBe(0);
    expect(volumeToHeight(5, 0, 40)).toBe(0);
  });

  it("刻度升序且都在域内", () => {
    const ticks = niceTicks({ min: 9.4, max: 20.6 }, 4);
    expect(ticks.length).toBeGreaterThan(2);
    for (let index = 1; index < ticks.length; index += 1) {
      expect(ticks[index]).toBeGreaterThan(ticks[index - 1]);
    }
    expect(ticks[0]).toBeGreaterThanOrEqual(9.4);
    expect(ticks[ticks.length - 1]).toBeLessThanOrEqual(20.6);
  });
});

describe("CHT-02 周期切换重算", () => {
  it("初始窗口显示最后 N 根，空数据不产生负窗口", () => {
    expect(initialWindow(24)).toEqual({ start: 0, end: 24 });
    expect(initialWindow(24, 10)).toEqual({ start: 14, end: 24 });
    expect(initialWindow(5, 10)).toEqual({ start: 0, end: 5 });
    expect(initialWindow(0)).toEqual({ start: 0, end: 0 });
  });

  it("槽宽随可见根数变化", () => {
    expect(slotWidth({ start: 0, end: 24 }, BOX)).toBeCloseTo(654 / 24, 6);
    expect(slotWidth({ start: 0, end: 12 }, BOX)).toBeCloseTo(654 / 12, 6);
  });

  it("日期标签等距采样且不重复", () => {
    expect(sampleIndices({ start: 0, end: 24 }, 6)).toEqual([0, 5, 9, 14, 18, 23]);
    expect(sampleIndices({ start: 0, end: 3 }, 6)).toEqual([0, 1, 2]);
    expect(sampleIndices({ start: 0, end: 0 }, 6)).toEqual([]);
  });
});

describe("CHT-03 缩放与平移边界", () => {
  it("以锚点为中心缩放", () => {
    expect(zoomWindow({ start: 0, end: 24 }, 24, 0.5, 12)).toEqual({
      start: 6,
      end: 18,
    });
  });

  it("缩到最小 10 根，最早期锚点贴左", () => {
    expect(zoomWindow({ start: 0, end: 12 }, 24, 0.5, 0)).toEqual({
      start: 0,
      end: 10,
    });
    expect(zoomWindow({ start: 8, end: 18 }, 24, 0.1, 12)).toEqual({
      start: 8,
      end: 18,
    });
  });

  it("放大到全量，不越过数组两端", () => {
    expect(zoomWindow({ start: 8, end: 18 }, 24, 10, 12)).toEqual({
      start: 0,
      end: 24,
    });
  });

  it("平移在两端被夹住", () => {
    expect(panWindow({ start: 0, end: 10 }, 24, -5)).toEqual({
      start: 0,
      end: 10,
    });
    expect(panWindow({ start: 10, end: 20 }, 24, 10)).toEqual({
      start: 14,
      end: 24,
    });
    expect(panWindow({ start: 10, end: 20 }, 24, 0)).toEqual({
      start: 10,
      end: 20,
    });
  });

  it("clampWindow 处理非法宽与越界起点", () => {
    expect(clampWindow({ start: 20, end: 40 }, 24)).toEqual({
      start: 4,
      end: 24,
    });
    expect(clampWindow({ start: 3, end: 3 }, 24)).toEqual({
      start: 3,
      end: 4,
    });
    expect(clampWindow({ start: 0, end: 5 }, 0)).toEqual({ start: 0, end: 0 });
  });
});

describe("CHT-06 午休时间轴与断线", () => {
  it("09:30 至 15:00 换算为 0 至 330 分钟", () => {
    expect(clockMinute("09:30")).toBe(0);
    expect(clockMinute("10:30")).toBe(60);
    expect(clockMinute("11:30")).toBe(120);
    expect(clockMinute("13:00")).toBe(210);
    expect(clockMinute("15:00")).toBe(SESSION_MINUTES);
    expect(clockMinute("8:00")).toBeNull();
    expect(clockMinute("16:00")).toBeNull();
    expect(clockMinute("bad")).toBeNull();
  });

  it("分钟与 x 轴可往返", () => {
    const x = minuteToX(60, BOX);
    expect(x).toBeCloseTo(128.9, 1);
    expect(xToMinute(x, BOX)).toBeCloseTo(60, 6);
  });

  it("跨午休视为断点", () => {
    expect(crossesSessionGap(110, 210, [[120, 210]])).toBe(true);
    expect(crossesSessionGap(120, 210, [[120, 210]])).toBe(true);
    expect(crossesSessionGap(120, 121, [[120, 210]])).toBe(false);
    expect(crossesSessionGap(210, 211, [[120, 210]])).toBe(false);
  });
});
