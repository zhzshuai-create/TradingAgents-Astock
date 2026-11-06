/** Pure chart geometry shared by the SVG charts (P4-08). No React, no DOM. */

import type { KlinePeriod } from "../../api/types";

export interface NumericDomain {
  min: number;
  max: number;
}

export interface PlotBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Index window over the bars array; `end` is exclusive. */
export interface BarWindow {
  start: number;
  end: number;
}

export const PERIOD_LABELS: Record<KlinePeriod, string> = {
  day: "日K",
  week: "周K",
  month: "月K",
};

/** 09:30 to 15:00, lunch included, in minutes. */
export const SESSION_MINUTES = 330;

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function extent(values: readonly number[]): NumericDomain | null {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const value of values) {
    if (Number.isFinite(value)) {
      min = Math.min(min, value);
      max = Math.max(max, value);
    }
  }
  return Number.isFinite(min) && Number.isFinite(max) ? { min, max } : null;
}

/** A flat domain still gets a visible band instead of a collapsed axis. */
export function padDomain(domain: NumericDomain, ratio = 0.06): NumericDomain {
  const span = domain.max - domain.min;
  const pad =
    span > 0 ? span * ratio : Math.max(Math.abs(domain.max) * 0.01, 0.5);
  return { min: domain.min - pad, max: domain.max + pad };
}

export function niceTicks(domain: NumericDomain, count = 5): number[] {
  const span = domain.max - domain.min;
  if (!Number.isFinite(span) || span <= 0) {
    return [domain.min];
  }
  const rawStep = span / count;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const residual = rawStep / magnitude;
  const niceResidual =
    residual <= 1 ? 1 : residual <= 2 ? 2 : residual <= 5 ? 5 : 10;
  const step = niceResidual * magnitude;
  const ticks: number[] = [];
  for (
    let value = Math.ceil(domain.min / step) * step;
    value <= domain.max + step * 1e-9;
    value += step
  ) {
    ticks.push(Number(value.toFixed(10)));
  }
  return ticks.length > 0 ? ticks : [domain.min, domain.max];
}

export function priceToY(
  price: number,
  domain: NumericDomain,
  box: PlotBox,
): number {
  const span = domain.max - domain.min;
  if (span <= 0) {
    return box.top + box.height / 2;
  }
  const ratio = (domain.max - clamp(price, domain.min, domain.max)) / span;
  return box.top + ratio * box.height;
}

export function volumeToHeight(
  volume: number,
  maxVolume: number,
  height: number,
): number {
  if (!(maxVolume > 0) || !Number.isFinite(volume) || volume <= 0) {
    return 0;
  }
  return (clamp(volume, 0, maxVolume) / maxVolume) * height;
}

export function visibleCount(window: BarWindow): number {
  return Math.max(0, window.end - window.start);
}

export function slotWidth(window: BarWindow, box: PlotBox): number {
  const count = visibleCount(window);
  return count > 0 ? box.width / count : 0;
}

export function indexToX(
  index: number,
  window: BarWindow,
  box: PlotBox,
): number {
  const count = visibleCount(window);
  if (count <= 0) {
    return box.left;
  }
  return box.left + ((index - window.start + 0.5) / count) * box.width;
}

export function xToIndex(
  x: number,
  window: BarWindow,
  box: PlotBox,
  total: number,
): number {
  if (total <= 0 || visibleCount(window) <= 0 || box.width <= 0) {
    return 0;
  }
  const ratio = clamp((x - box.left) / box.width, 0, 0.999999);
  const index = window.start + Math.floor(ratio * visibleCount(window));
  return clamp(index, window.start, Math.min(window.end, total) - 1);
}

/** Show the latest bars by default, like a trading terminal. */
export function initialWindow(total: number, visible = total): BarWindow {
  if (total <= 0) {
    return { start: 0, end: 0 };
  }
  const count = clamp(Math.round(visible), 1, total);
  return { start: total - count, end: total };
}

export function minVisibleCount(total: number): number {
  return Math.min(total, 10);
}

export function clampWindow(window: BarWindow, total: number): BarWindow {
  if (total <= 0) {
    return { start: 0, end: 0 };
  }
  const count = clamp(window.end - window.start, 1, total);
  const start = clamp(window.start, 0, total - count);
  return { start, end: start + count };
}

/** factor < 1 zooms in; the anchor bar keeps its relative position. */
export function zoomWindow(
  window: BarWindow,
  total: number,
  factor: number,
  anchorIndex: number,
): BarWindow {
  const count = visibleCount(window);
  if (count <= 0 || !(factor > 0)) {
    return clampWindow(window, total);
  }
  const nextCount = clamp(
    Math.round(count * factor),
    minVisibleCount(total),
    total,
  );
  if (nextCount === count) {
    return clampWindow(window, total);
  }
  const anchor = clamp(anchorIndex, window.start, window.end - 1);
  const ratio = count <= 1 ? 0 : (anchor - window.start) / count;
  const start = Math.round(anchor - ratio * nextCount);
  return clampWindow({ start, end: start + nextCount }, total);
}

/** Positive `deltaBars` moves the window later in time. */
export function panWindow(
  window: BarWindow,
  total: number,
  deltaBars: number,
): BarWindow {
  if (!Number.isFinite(deltaBars) || deltaBars === 0) {
    return clampWindow(window, total);
  }
  return clampWindow(
    {
      start: window.start + Math.round(deltaBars),
      end: window.end + Math.round(deltaBars),
    },
    total,
  );
}

/** Evenly spaced indices for date labels, duplicates removed. */
export function sampleIndices(window: BarWindow, max: number): number[] {
  const count = visibleCount(window);
  if (count <= 0 || max <= 0) {
    return [];
  }
  if (count <= max) {
    return Array.from({ length: count }, (_, offset) => window.start + offset);
  }
  const seen = new Set<number>();
  for (let slot = 0; slot < max; slot += 1) {
    seen.add(window.start + Math.round((slot * (count - 1)) / (max - 1)));
  }
  return [...seen].sort((left, right) => left - right);
}

export function formatChartPrice(value: number): string {
  if (!Number.isFinite(value)) {
    return "—";
  }
  return value.toFixed(2);
}

export function formatChartVolume(value: number): string {
  if (!Number.isFinite(value)) {
    return "—";
  }
  const absolute = Math.abs(value);
  if (absolute >= 1e8) {
    return `${(value / 1e8).toFixed(2)}亿`;
  }
  if (absolute >= 1e4) {
    return `${(value / 1e4).toFixed(2)}万`;
  }
  return value.toFixed(0);
}

export function formatChangePct(
  current: number,
  previous: number | null,
): string {
  if (
    previous === null ||
    !Number.isFinite(previous) ||
    previous === 0 ||
    !Number.isFinite(current)
  ) {
    return "—";
  }
  const pct = ((current - previous) / previous) * 100;
  return `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

/** ISO timestamps keep their server-side offset; slicing avoids timezone drift. */
export function formatChartTime(iso: string | null): string {
  if (iso === null || iso.length < 16) {
    return "—";
  }
  return iso.slice(0, 16).replace("T", " ");
}

/** Minutes since 09:30, lunch included; null outside the session. */
export function clockMinute(time: string): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(time.trim());
  if (match === null) {
    return null;
  }
  const minutes = Number(match[1]) * 60 + Number(match[2]);
  const open = 9 * 60 + 30;
  const close = 15 * 60;
  if (minutes < open || minutes > close) {
    return null;
  }
  return minutes - open;
}

export function minuteToX(minute: number, box: PlotBox): number {
  return box.left + (clamp(minute, 0, SESSION_MINUTES) / SESSION_MINUTES) * box.width;
}

export function xToMinute(x: number, box: PlotBox): number {
  if (box.width <= 0) {
    return 0;
  }
  return clamp((x - box.left) / box.width, 0, 1) * SESSION_MINUTES;
}

/** Lunch (or any session gap) is left unconnected, never interpolated. */
export function crossesSessionGap(
  previousMinute: number,
  currentMinute: number,
  gaps: ReadonlyArray<readonly [number, number]>,
): boolean {
  return gaps.some(
    ([start, end]) => previousMinute <= start && currentMinute >= end,
  );
}
