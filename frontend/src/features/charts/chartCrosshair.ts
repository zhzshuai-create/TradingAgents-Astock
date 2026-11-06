/** Crosshair snapping shared by both charts (P4-08). */

import {
  clamp,
  indexToX,
  xToIndex,
  type BarWindow,
  type NumericDomain,
  type PlotBox,
} from "./chartScale";

export interface CrosshairPoint {
  index: number;
  x: number;
}

/** Snap a pointer x (viewBox units) to the nearest visible bar centre. */
export function snapToBar(
  x: number,
  window: BarWindow,
  box: PlotBox,
  total: number,
): CrosshairPoint | null {
  if (total <= 0 || window.end <= window.start || box.width <= 0) {
    return null;
  }
  const index = xToIndex(x, window, box, total);
  return { index, x: indexToX(index, window, box) };
}

export function yToPrice(
  y: number,
  domain: NumericDomain,
  box: PlotBox,
): number {
  if (box.height <= 0) {
    return domain.max;
  }
  const ratio = clamp((y - box.top) / box.height, 0, 1);
  return domain.max - ratio * (domain.max - domain.min);
}

/** Used by the intraday chart, where x positions are time based. */
export function nearestPointIndex(xs: readonly number[], x: number): number {
  if (xs.length === 0) {
    return -1;
  }
  let best = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < xs.length; index += 1) {
    const distance = Math.abs(xs[index] - x);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = index;
    }
  }
  return best;
}
