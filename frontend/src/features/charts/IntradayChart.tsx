import { useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import type { IntradayData } from "../../api/types";
import { EmptyState } from "../../ui";
import { nearestPointIndex } from "./chartCrosshair";
import {
  clamp,
  clockMinute,
  crossesSessionGap,
  extent,
  formatChartPrice,
  formatChartTime,
  formatChartVolume,
  minuteToX,
  niceTicks,
  padDomain,
  priceToY,
  SESSION_MINUTES,
  volumeToHeight,
  type PlotBox,
} from "./chartScale";
import styles from "./Charts.module.css";

const VIEW_WIDTH = 720;
const VIEW_HEIGHT = 300;

const PRICE_BOX: PlotBox = { left: 10, top: 26, width: 654, height: 190 };
const VOLUME_BOX: PlotBox = { left: 10, top: 236, width: 654, height: 40 };
const AXIS_X = VIEW_WIDTH - 6;

export interface IntradayChartProps {
  data: IntradayData;
  asOf?: string | null;
  fetchedAt?: string | null;
}

interface PlottedPoint {
  time: string;
  minute: number;
  price: number;
  volume: number;
  avgPrice: number | null;
}

interface SegmentEntry {
  minute: number;
  value: number | null;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function minuteLabel(minute: number): string {
  const absolute = minute + 9 * 60 + 30;
  return `${pad(Math.floor(absolute / 60))}:${pad(absolute % 60)}`;
}

export function buildSegments(
  entries: ReadonlyArray<SegmentEntry>,
  gaps: ReadonlyArray<readonly [number, number]>,
): number[][] {
  const segments: number[][] = [];
  let current: number[] = [];
  for (let index = 0; index < entries.length; index += 1) {
    const entry = entries[index];
    if (entry.value === null) {
      if (current.length > 0) {
        segments.push(current);
        current = [];
      }
      continue;
    }
    const previous =
      current.length > 0 ? entries[current[current.length - 1]] : null;
    if (previous !== null) {
      const broken = crossesSessionGap(previous.minute, entry.minute, gaps);
      if (broken) {
        segments.push(current);
        current = [];
      }
    }
    current.push(index);
  }
  if (current.length > 0) {
    segments.push(current);
  }
  return segments;
}

export function IntradayChart({
  data,
  asOf = null,
  fetchedAt = null,
}: IntradayChartProps) {
  const [showPrice, setShowPrice] = useState(true);
  const [showAverage, setShowAverage] = useState(true);
  const [showVolume, setShowVolume] = useState(true);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const plotted = useMemo<PlottedPoint[]>(
    () =>
      data.points.flatMap((point) => {
        const minute = clockMinute(point.time);
        if (minute === null) {
          return [];
        }
        return [
          {
            time: point.time,
            minute,
            price: point.price,
            volume: point.volume,
            avgPrice: point.avg_price,
          },
        ];
      }),
    [data.points],
  );

  const gaps = useMemo<[number, number][]>(
    () =>
      data.session_gaps.flatMap(([start, end]) => {
        const startMinute = clockMinute(start);
        const endMinute = clockMinute(end);
        return startMinute === null || endMinute === null
          ? []
          : [[startMinute, endMinute] as [number, number]];
      }),
    [data.session_gaps],
  );

  const priceSegments = useMemo(
    () =>
      buildSegments(
        plotted.map((point) => ({ minute: point.minute, value: point.price })),
        gaps,
      ),
    [gaps, plotted],
  );

  const averageSegments = useMemo(
    () =>
      buildSegments(
        plotted.map((point) => ({
          minute: point.minute,
          value: point.avgPrice,
        })),
        gaps,
      ),
    [gaps, plotted],
  );

  const priceDomain = useMemo(() => {
    const prices = plotted.flatMap((point) =>
      point.avgPrice === null
        ? [point.price]
        : [point.price, point.avgPrice],
    );
    return padDomain(extent(prices) ?? { min: 0, max: 1 });
  }, [plotted]);

  const volumeMax = useMemo(
    () => Math.max(0, ...plotted.map((point) => point.volume)),
    [plotted],
  );

  const ticks = useMemo(() => niceTicks(priceDomain, 4), [priceDomain]);

  const xs = useMemo(
    () => plotted.map((point) => minuteToX(point.minute, PRICE_BOX)),
    [plotted],
  );

  const barWidth = useMemo(
    () => clamp((PRICE_BOX.width / Math.max(plotted.length, 1)) * 0.6, 1, 6),
    [plotted.length],
  );

  const timeLabels = useMemo(() => {
    const labels = [{ minute: 0, label: "09:30" }];
    for (const [start, end] of gaps) {
      labels.push({ minute: start, label: minuteLabel(start) });
      labels.push({ minute: end, label: minuteLabel(end) });
    }
    labels.push({ minute: SESSION_MINUTES, label: "15:00" });
    return labels;
  }, [gaps]);

  function pointerX(clientX: number): number {
    const svg = svgRef.current;
    if (svg === null) {
      return 0;
    }
    const rect = svg.getBoundingClientRect();
    const scale = rect.width > 0 ? VIEW_WIDTH / rect.width : 1;
    return (clientX - rect.left) * scale;
  }

  function handlePointerMove(event: ReactPointerEvent<SVGRectElement>) {
    const index = nearestPointIndex(xs, pointerX(event.clientX));
    setHoverIndex(index === -1 ? null : index);
  }

  const readoutIndex = hoverIndex ?? plotted.length - 1;
  const readout = plotted[readoutIndex];
  const hoverX = hoverIndex === null ? null : xs[hoverIndex];

  // Facts already in the payload: no extra request, no invented numbers.
  const summary = useMemo(() => {
    if (plotted.length === 0) {
      return null;
    }
    const prices = plotted.map((point) => point.price);
    return {
      last: plotted[plotted.length - 1],
      low: Math.min(...prices),
      high: Math.max(...prices),
      start: plotted[0].time,
    };
  }, [plotted]);

  return (
    <figure
      className={styles.root}
      data-testid="intraday-chart"
      data-points={data.points.length}
      data-date={data.date}
      data-gaps={data.session_gaps.length}
    >
      <header className={styles.header}>
        <div className={styles.headRow}>
          <div className={styles.legend} role="group" aria-label="图例">
            <button
              type="button"
              className={styles.toolButton}
              data-testid="intraday-legend-price"
              aria-pressed={showPrice}
              onClick={() => setShowPrice((value) => !value)}
            >
              价格
            </button>
            <button
              type="button"
              className={styles.toolButton}
              data-testid="intraday-legend-avg"
              aria-pressed={showAverage}
              onClick={() => setShowAverage((value) => !value)}
            >
              均价
            </button>
            <button
              type="button"
              className={styles.toolButton}
              data-testid="intraday-legend-volume"
              aria-pressed={showVolume}
              onClick={() => setShowVolume((value) => !value)}
            >
              成交量
            </button>
          </div>
          <span className={styles.meta} data-testid="intraday-meta">
            {data.date} · 数据时间 {formatChartTime(asOf ?? fetchedAt)}
          </span>
        </div>
        {plotted.length > 0 ? (
          <p
            className={styles.readout}
            data-testid="intraday-readout"
            data-index={readoutIndex}
            data-snapped={hoverIndex === null ? "false" : "true"}
          >
            时间{" "}
            <span className={styles.readoutValue}>{readout.time}</span> 价{" "}
            <span className={styles.readoutValue}>
              {formatChartPrice(readout.price)}
            </span>{" "}
            均{" "}
            <span className={styles.readoutValue}>
              {readout.avgPrice === null
                ? "—"
                : formatChartPrice(readout.avgPrice)}
            </span>{" "}
            量{" "}
            <span className={styles.readoutValue}>
              {formatChartVolume(readout.volume)}手
            </span>
          </p>
        ) : null}
      </header>

      {plotted.length === 0 ? (
        <div className={styles.empty} data-testid="intraday-empty">
          <EmptyState
            title="暂无分时数据"
            description="该日期没有可用的分时数据。"
          />
        </div>
      ) : (
        <div
          className={styles.scroll}
          data-testid="intraday-scroll"
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
                ? `${data.date} 分时图`
                : `${data.date} 分时图，共 ${plotted.length} 个点，最新 ${formatChartPrice(summary.last.price)} 元，最低 ${formatChartPrice(summary.low)} 元，最高 ${formatChartPrice(summary.high)} 元`
            }
            data-chart="intraday"
            data-points={data.points.length}
            data-segments={priceSegments.length}
            data-gaps={data.session_gaps.length}
            data-date={data.date}
          >
            {gaps.map(([start, end]) => {
              const left = minuteToX(start, PRICE_BOX);
              const width = minuteToX(end, PRICE_BOX) - left;
              return (
                <g key={`gap-${start}`} data-role="session-gap">
                  <rect
                    data-role="lunch-gap"
                    className={styles.lunchBand}
                    x={left}
                    y={PRICE_BOX.top}
                    width={width}
                    height={
                      VOLUME_BOX.top + VOLUME_BOX.height - PRICE_BOX.top
                    }
                  />
                  <line
                    className={styles.lunchEdge}
                    x1={left}
                    x2={left}
                    y1={PRICE_BOX.top}
                    y2={VOLUME_BOX.top + VOLUME_BOX.height}
                  />
                  <line
                    className={styles.lunchEdge}
                    x1={left + width}
                    x2={left + width}
                    y1={PRICE_BOX.top}
                    y2={VOLUME_BOX.top + VOLUME_BOX.height}
                  />
                </g>
              );
            })}

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

            {showVolume
              ? plotted.map((point, index) => {
                  const height = volumeToHeight(
                    point.volume,
                    volumeMax,
                    VOLUME_BOX.height,
                  );
                  const previous = index > 0 ? plotted[index - 1] : null;
                  const direction =
                    previous === null || point.price === previous.price
                      ? "flat"
                      : point.price > previous.price
                        ? "up"
                        : "down";
                  return (
                    <rect
                      key={`volume-${point.time}-${index}`}
                      data-role="volume-bar"
                      data-index={index}
                      data-direction={direction}
                      data-height={height}
                      className={`${styles.volumeBar} ${
                        direction === "up"
                          ? styles.up
                          : direction === "down"
                            ? styles.down
                            : styles.flat
                      }`}
                      x={xs[index] - barWidth / 2}
                      y={VOLUME_BOX.top + VOLUME_BOX.height - height}
                      width={barWidth}
                      height={height}
                    />
                  );
                })
              : null}

            {showAverage
              ? averageSegments.map((segment, segmentIndex) => {
                  const points = segment
                    .map((pointIndex) => {
                      const point = plotted[pointIndex];
                      return `${minuteToX(point.minute, PRICE_BOX).toFixed(
                        2,
                      )},${priceToY(
                        point.avgPrice ?? point.price,
                        priceDomain,
                        PRICE_BOX,
                      ).toFixed(2)}`;
                    })
                    .join(" ");
                  if (segment.length < 2) {
                    return null;
                  }
                  return (
                    <polyline
                      key={`avg-${segmentIndex}`}
                      data-role="avg-line"
                      data-segment={segmentIndex}
                      className={styles.avgLine}
                      points={points}
                    />
                  );
                })
              : null}

            {showPrice
              ? priceSegments.map((segment, segmentIndex) => {
                  if (segment.length < 2) {
                    const point = plotted[segment[0]];
                    return (
                      <circle
                        key={`dot-${segmentIndex}`}
                        data-role="price-dot"
                        data-index={segment[0]}
                        className={styles.priceDot}
                        cx={minuteToX(point.minute, PRICE_BOX)}
                        cy={priceToY(point.price, priceDomain, PRICE_BOX)}
                        r={2.5}
                      />
                    );
                  }
                  const points = segment
                    .map((pointIndex) => {
                      const point = plotted[pointIndex];
                      return `${minuteToX(point.minute, PRICE_BOX).toFixed(
                        2,
                      )},${priceToY(
                        point.price,
                        priceDomain,
                        PRICE_BOX,
                      ).toFixed(2)}`;
                    })
                    .join(" ");
                  return (
                    <polyline
                      key={`price-${segmentIndex}`}
                      data-role="price-line"
                      data-segment={segmentIndex}
                      className={styles.priceLine}
                      points={points}
                    />
                  );
                })
              : null}

            {timeLabels.map((tick) => (
              <text
                key={`time-${tick.minute}`}
                data-role="time-label"
                data-minute={tick.minute}
                className={styles.axisText}
                x={minuteToX(tick.minute, PRICE_BOX)}
                y={VIEW_HEIGHT - 6}
                textAnchor={
                  tick.minute === 0
                    ? "start"
                    : tick.minute === SESSION_MINUTES
                      ? "end"
                      : "middle"
                }
              >
                {tick.label}
              </text>
            ))}

            {hoverX !== null ? (
              <g data-role="crosshair" data-index={hoverIndex}>
                <line
                  className={styles.crosshair}
                  x1={hoverX}
                  x2={hoverX}
                  y1={PRICE_BOX.top}
                  y2={VOLUME_BOX.top + VOLUME_BOX.height}
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
              onPointerMove={handlePointerMove}
              onPointerLeave={() => setHoverIndex(null)}
            />
          </svg>
        </div>
      )}
      {summary === null ? null : (
        <figcaption className="sr-only" data-testid="intraday-summary">
          {data.date} 分时，{summary.start} 至 {summary.last.time}，共{" "}
          {plotted.length} 个点；最新价 {formatChartPrice(summary.last.price)}{" "}
          元，区间最低 {formatChartPrice(summary.low)} 元，最高{" "}
          {formatChartPrice(summary.high)} 元。
        </figcaption>
      )}
    </figure>
  );
}
