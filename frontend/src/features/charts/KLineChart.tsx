import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import type { KlineBar, KlineData, KlinePeriod } from "../../api/types";
import { EmptyState } from "../../ui";
import { snapToBar, type CrosshairPoint } from "./chartCrosshair";
import {
  clamp,
  extent,
  formatChangePct,
  formatChartPrice,
  formatChartTime,
  formatChartVolume,
  indexToX,
  initialWindow,
  niceTicks,
  padDomain,
  panWindow,
  PERIOD_LABELS,
  priceToY,
  sampleIndices,
  slotWidth,
  volumeToHeight,
  zoomWindow,
  type BarWindow,
  type PlotBox,
} from "./chartScale";
import styles from "./Charts.module.css";

const VIEW_WIDTH = 720;
const VIEW_HEIGHT = 320;

const PRICE_BOX: PlotBox = { left: 10, top: 30, width: 654, height: 176 };
const VOLUME_BOX: PlotBox = { left: 10, top: 226, width: 654, height: 56 };
const AXIS_X = VIEW_WIDTH - 6;
const PERIODS: KlinePeriod[] = ["day", "week", "month"];

export interface KLineChartProps {
  data: KlineData;
  period: KlinePeriod;
  onPeriodChange?: (period: KlinePeriod) => void;
  asOf?: string | null;
  fetchedAt?: string | null;
  /** Bars shown before the user zooms; defaults to every loaded bar. */
  initialCount?: number;
  /** Below 767px zoom/pan gestures are off; periods and scrolling take over. */
  mobile?: boolean;
}

type Direction = "up" | "down" | "flat";

const TONE: Record<Direction, string> = {
  up: styles.up,
  down: styles.down,
  flat: styles.flat,
};

function directionOf(bar: KlineBar): Direction {
  if (bar.close === bar.open) {
    return "flat";
  }
  return bar.close > bar.open ? "up" : "down";
}

function formatDateLabel(date: string): string {
  return date.length >= 10 ? date.slice(5) : date;
}

export function KLineChart({
  data,
  period,
  onPeriodChange,
  asOf = null,
  fetchedAt = null,
  initialCount,
  mobile = false,
}: KLineChartProps) {
  const bars = data.bars;
  const total = bars.length;

  const [barWindow, setBarWindow] = useState<BarWindow>(() =>
    initialWindow(total, initialCount),
  );
  const [showCandles, setShowCandles] = useState(true);
  const [showVolume, setShowVolume] = useState(true);
  const [hover, setHover] = useState<CrosshairPoint | null>(null);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    window: BarWindow;
  } | null>(null);

  useEffect(() => {
    setBarWindow(initialWindow(total, initialCount));
    setHover(null);
  }, [period, total, initialCount]);

  const visibleBars = useMemo(
    () => bars.slice(barWindow.start, barWindow.end),
    [bars, barWindow],
  );

  const priceDomain = useMemo(() => {
    const prices = visibleBars.flatMap((bar) => [bar.high, bar.low]);
    return padDomain(extent(prices) ?? { min: 0, max: 1 });
  }, [visibleBars]);

  const volumeMax = useMemo(
    () => Math.max(0, ...visibleBars.map((bar) => bar.volume)),
    [visibleBars],
  );

  const ticks = useMemo(() => niceTicks(priceDomain, 4), [priceDomain]);
  const labelIndices = useMemo(() => sampleIndices(barWindow, 6), [barWindow]);
  const bodyWidth = useMemo(
    () => clamp(slotWidth(barWindow, PRICE_BOX) * 0.62, 1, 24),
    [barWindow],
  );

  // React's wheel listener is passive; prevent page scroll with a native one.
  useEffect(() => {
    if (mobile) {
      return undefined;
    }
    const svg = svgRef.current;
    if (svg === null || total === 0) {
      return undefined;
    }
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = svg.getBoundingClientRect();
      const scale = rect.width > 0 ? VIEW_WIDTH / rect.width : 1;
      const x = (event.clientX - rect.left) * scale;
      const factor = event.deltaY < 0 ? 1 / 1.25 : 1.25;
      setBarWindow((current) => {
        const anchor =
          snapToBar(x, current, PRICE_BOX, total)?.index ?? current.end - 1;
        return zoomWindow(current, total, factor, anchor);
      });
      setHover(null);
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, [total, mobile]);

  function pointerX(clientX: number): number {
    const svg = svgRef.current;
    if (svg === null) {
      return 0;
    }
    const rect = svg.getBoundingClientRect();
    const scale = rect.width > 0 ? VIEW_WIDTH / rect.width : 1;
    return (clientX - rect.left) * scale;
  }

  function handlePointerDown(event: ReactPointerEvent<SVGRectElement>) {
    if (event.pointerType === "touch" || event.pointerType === "pen") {
      return;
    }
    dragRef.current = {
      pointerId: event.pointerId ?? 0,
      startX: event.clientX,
      window: barWindow,
    };
    const target = event.currentTarget;
    if (typeof target.setPointerCapture === "function") {
      target.setPointerCapture(event.pointerId ?? 0);
    }
  }

  function handlePointerMove(event: ReactPointerEvent<SVGRectElement>) {
    const x = pointerX(event.clientX);
    setHover(snapToBar(x, barWindow, PRICE_BOX, total));

    const drag = dragRef.current;
    if (drag === null) {
      return;
    }
    const step = slotWidth(barWindow, PRICE_BOX);
    if (step <= 0) {
      return;
    }
    const deltaBars = Math.round(-(x - pointerX(drag.startX)) / step);
    setBarWindow(panWindow(drag.window, total, deltaBars));
  }

  function endDrag(event: ReactPointerEvent<SVGRectElement>) {
    dragRef.current = null;
    const target = event.currentTarget;
    if (typeof target.releasePointerCapture === "function") {
      target.releasePointerCapture(event.pointerId ?? 0);
    }
  }

  const readoutIndex = hover?.index ?? barWindow.end - 1;
  const readoutBar = bars[readoutIndex];
  const readoutPrevious =
    readoutIndex > 0 && bars[readoutIndex - 1] !== undefined
      ? bars[readoutIndex - 1].close
      : null;

  // Describes the visible window only, from bars already in the payload.
  const summary = useMemo(() => {
    const first = visibleBars[0];
    const last = visibleBars[visibleBars.length - 1];
    if (first === undefined || last === undefined) {
      return null;
    }
    const previousIndex = barWindow.start + visibleBars.length - 2;
    const previous =
      previousIndex >= 0 ? (bars[previousIndex]?.close ?? null) : null;
    return {
      first,
      last,
      change: formatChangePct(last.close, previous),
    };
  }, [bars, barWindow.start, visibleBars]);

  const header = (
    <header className={styles.header}>
      <div className={styles.headRow}>
        <div className={styles.periods} role="group" aria-label="K 线周期">
          {PERIODS.map((value) => (
            <button
              key={value}
              type="button"
              className={styles.toolButton}
              data-testid={`kline-period-${value}`}
              aria-pressed={period === value}
              onClick={() => onPeriodChange?.(value)}
            >
              {PERIOD_LABELS[value]}
            </button>
          ))}
        </div>
        <div className={styles.legend} role="group" aria-label="图例">
          <button
            type="button"
            className={styles.toolButton}
            data-testid="kline-legend-candles"
            aria-pressed={showCandles}
            onClick={() => setShowCandles((value) => !value)}
          >
            K线
          </button>
          <button
            type="button"
            className={styles.toolButton}
            data-testid="kline-legend-volume"
            aria-pressed={showVolume}
            onClick={() => setShowVolume((value) => !value)}
          >
            成交量
          </button>
        </div>
      </div>
      <div className={styles.metaRow}>
        <p
          className={styles.readout}
          data-testid="kline-readout"
          data-index={readoutIndex}
          data-snapped={hover === null ? "false" : "true"}
        >
          {readoutBar === undefined ? (
            "—"
          ) : (
            <>
              <span className={styles.readoutValue}>{readoutBar.date}</span> 开{" "}
              <span className={styles.readoutValue}>
                {formatChartPrice(readoutBar.open)}
              </span>{" "}
              高{" "}
              <span className={styles.readoutValue}>
                {formatChartPrice(readoutBar.high)}
              </span>{" "}
              低{" "}
              <span className={styles.readoutValue}>
                {formatChartPrice(readoutBar.low)}
              </span>{" "}
              收{" "}
              <span className={styles.readoutValue}>
                {formatChartPrice(readoutBar.close)}
              </span>{" "}
              涨跌{" "}
              <span className={styles.readoutValue}>
                {formatChangePct(readoutBar.close, readoutPrevious)}
              </span>{" "}
              量{" "}
              <span className={styles.readoutValue}>
                {formatChartVolume(readoutBar.volume)}手
              </span>{" "}
              额{" "}
              <span className={styles.readoutValue}>
                {readoutBar.amount === null
                  ? "—"
                  : formatChartVolume(readoutBar.amount)}
              </span>
            </>
          )}
        </p>
        <span className={styles.meta} data-testid="kline-meta">
          <span className={styles.adjustTag} data-adjust={data.adjust}>
            不复权
          </span>
          {" · "}
          数据时间 {formatChartTime(asOf ?? fetchedAt)}
        </span>
      </div>
      <p className={styles.hint} data-testid="kline-hint" data-mobile={mobile}>
        {mobile ? "周期按钮切换 · 图表可横向滑动 · " : "滚轮缩放 · 拖拽平移 · "}
        <span
          data-testid="kline-window"
          data-start={barWindow.start}
          data-end={barWindow.end}
          data-count={barWindow.end - barWindow.start}
        >
          {barWindow.start + 1}–{barWindow.end} / {total}
        </span>{" "}
        根
      </p>
    </header>
  );

  return (
    <figure
      className={styles.root}
      data-testid="kline-chart"
      data-bars={total}
      data-period={period}
      data-adjust={data.adjust}
    >
      {header}
      {total === 0 ? (
        <div className={styles.empty} data-testid="kline-empty">
          <EmptyState
            title="暂无 K 线数据"
            description="该周期没有可用的 K 线。"
          />
        </div>
      ) : (
        <div
          className={styles.scroll}
          data-testid="kline-scroll"
          data-scroll="x"
          style={{ overflowX: "auto", minWidth: 0, maxWidth: "100%" }}
        >
          <svg
            ref={svgRef}
            className={styles.svg}
            style={{ minWidth: 640 }}
            viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
            role="img"
            aria-label={
              summary === null
                ? `${PERIOD_LABELS[period]} K 线，共 ${total} 根`
                : `${PERIOD_LABELS[period]} K 线，${summary.first.date} 至 ${summary.last.date} 共 ${visibleBars.length} 根，最新收盘 ${formatChartPrice(summary.last.close)} 元，涨跌 ${summary.change}`
            }
            data-chart="kline"
            data-bars={total}
            data-period={period}
            data-window-start={barWindow.start}
            data-window-end={barWindow.end}
            data-adjust={data.adjust}
          >
            {ticks.map((tick) => {
              const y = priceToY(tick, priceDomain, PRICE_BOX);
              return (
                <g key={tick} data-role="price-tick" data-value={tick}>
                  <line
                    className={styles.grid}
                    x1={PRICE_BOX.left}
                    x2={PRICE_BOX.left + PRICE_BOX.width}
                    y1={y}
                    y2={y}
                  />
                  <text
                    className={styles.axisText}
                    x={AXIS_X}
                    y={y + 4}
                    textAnchor="end"
                  >
                    {formatChartPrice(tick)}
                  </text>
                </g>
              );
            })}

            <line
              className={styles.axisFrame}
              x1={PRICE_BOX.left}
              x2={PRICE_BOX.left}
              y1={PRICE_BOX.top}
              y2={PRICE_BOX.top + PRICE_BOX.height}
            />
            <line
              className={styles.axisFrame}
              x1={VOLUME_BOX.left}
              x2={VOLUME_BOX.left}
              y1={VOLUME_BOX.top}
              y2={VOLUME_BOX.top + VOLUME_BOX.height}
            />

            {showCandles
              ? visibleBars.map((bar, offset) => {
                  const index = barWindow.start + offset;
                  const x = indexToX(index, barWindow, PRICE_BOX);
                  const direction = directionOf(bar);
                  const yOpen = priceToY(bar.open, priceDomain, PRICE_BOX);
                  const yClose = priceToY(bar.close, priceDomain, PRICE_BOX);
                  const top = Math.min(yOpen, yClose);
                  const bodyHeight = Math.max(Math.abs(yOpen - yClose), 1);
                  return (
                    <g
                      key={bar.date}
                      data-role="candle"
                      data-index={index}
                      data-date={bar.date}
                      data-direction={direction}
                    >
                      <line
                        data-role="wick"
                        className={`${styles.wick} ${TONE[direction]}`}
                        x1={x}
                        x2={x}
                        y1={priceToY(bar.high, priceDomain, PRICE_BOX)}
                        y2={priceToY(bar.low, priceDomain, PRICE_BOX)}
                      />
                      <rect
                        data-role="body"
                        className={`${styles.body} ${TONE[direction]}`}
                        x={x - bodyWidth / 2}
                        y={top}
                        width={bodyWidth}
                        height={bodyHeight}
                      />
                    </g>
                  );
                })
              : null}

            {showVolume
              ? visibleBars.map((bar, offset) => {
                  const index = barWindow.start + offset;
                  const height = volumeToHeight(
                    bar.volume,
                    volumeMax,
                    VOLUME_BOX.height,
                  );
                  const direction = directionOf(bar);
                  return (
                    <rect
                      key={bar.date}
                      data-role="volume-bar"
                      data-index={index}
                      data-direction={direction}
                      data-height={height}
                      className={`${styles.volumeBar} ${TONE[direction]}`}
                      x={indexToX(index, barWindow, VOLUME_BOX) - bodyWidth / 2}
                      y={VOLUME_BOX.top + VOLUME_BOX.height - height}
                      width={bodyWidth}
                      height={height}
                    />
                  );
                })
              : null}

            {labelIndices.map((index) => {
              const bar = bars[index];
              if (bar === undefined) {
                return null;
              }
              return (
                <text
                  key={`label-${bar.date}`}
                  data-role="date-label"
                  className={styles.axisText}
                  x={indexToX(index, barWindow, PRICE_BOX)}
                  y={VIEW_HEIGHT - 6}
                  textAnchor="middle"
                >
                  {formatDateLabel(bar.date)}
                </text>
              );
            })}

            {hover !== null && bars[hover.index] !== undefined ? (
              <g data-role="crosshair" data-index={hover.index}>
                <line
                  className={styles.crosshair}
                  x1={hover.x}
                  x2={hover.x}
                  y1={PRICE_BOX.top}
                  y2={VOLUME_BOX.top + VOLUME_BOX.height}
                />
                <line
                  data-role="crosshair-h"
                  className={styles.crosshair}
                  x1={PRICE_BOX.left}
                  x2={PRICE_BOX.left + PRICE_BOX.width}
                  y1={priceToY(bars[hover.index].close, priceDomain, PRICE_BOX)}
                  y2={priceToY(bars[hover.index].close, priceDomain, PRICE_BOX)}
                />
              </g>
            ) : null}

            <rect
              data-role="hit-area"
              x={PRICE_BOX.left}
              y={PRICE_BOX.top}
              width={PRICE_BOX.width}
              height={VOLUME_BOX.top + VOLUME_BOX.height - PRICE_BOX.top}
              fill="transparent"
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
              onPointerLeave={() => setHover(null)}
            />
          </svg>
        </div>
      )}
      {summary === null ? null : (
        <figcaption className="sr-only" data-testid="kline-summary">
          {PERIOD_LABELS[period]} K 线，{summary.first.date} 至{" "}
          {summary.last.date}，共 {visibleBars.length} 根；最新收盘{" "}
          {formatChartPrice(summary.last.close)} 元，涨跌 {summary.change}。
        </figcaption>
      )}
    </figure>
  );
}
