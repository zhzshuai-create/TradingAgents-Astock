import { describe, expect, it } from "vitest";

import {
  nearestPointIndex,
  snapToBar,
  yToPrice,
} from "./chartCrosshair";

const BOX = { left: 10, top: 0, width: 654, height: 100 };

describe("CHT-04 十字光标吸附", () => {
  it("吸附到最近一根 K 线的中心", () => {
    const point = snapToBar(105, { start: 0, end: 24 }, BOX, 24);
    expect(point).not.toBeNull();
    expect(point?.index).toBe(3);
    expect(point?.x).toBeCloseTo(10 + 3.5 * (654 / 24), 6);
  });

  it("两侧越界被夹在第一根与最后一根", () => {
    expect(snapToBar(-500, { start: 0, end: 24 }, BOX, 24)?.index).toBe(0);
    expect(snapToBar(5000, { start: 0, end: 24 }, BOX, 24)?.index).toBe(23);
  });

  it("空窗口没有吸附点", () => {
    expect(snapToBar(100, { start: 0, end: 0 }, BOX, 0)).toBeNull();
  });

  it("y 反算价格并夹在域内", () => {
    const domain = { min: 10, max: 20 };
    expect(yToPrice(50, domain, BOX)).toBeCloseTo(15, 6);
    expect(yToPrice(-20, domain, BOX)).toBe(20);
    expect(yToPrice(200, domain, BOX)).toBe(10);
  });

  it("按 x 距离选最近的分时点", () => {
    expect(nearestPointIndex([10, 100, 200], 120)).toBe(1);
    expect(nearestPointIndex([10, 100, 200], 1000)).toBe(2);
    expect(nearestPointIndex([], 5)).toBe(-1);
  });
});
