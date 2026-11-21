import { useIsFetching } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import styles from "./Splash.module.css";
import { THEME_STORAGE_KEY } from "./useTheme";

/**
 * Boot plate: a printed chart, not a loading show.
 *
 * The app is paper and ink — warm grey canvas, every mark is ink, the only
 * saturated colours in the product are the red and green of A-share movement.
 * So the overlay opens on the same paper instead of a black stage, and the boot
 * story is told as a candlestick chart: the baseline is ruled in, seven candles
 * print one after another — one per analyst — the decision rule crosses at the
 * last close, the last candle's wick breaks through it, and the wordmark locks
 * up. 1.42s, then the cover dissolves and the page rises out of the paper.
 *
 * Seven candles, not four bars, because the pipeline really has seven analysts:
 * the count is the product's own structure. Bodies are hollow when the candle
 * closes up and filled when it closes down, the way a chart is printed in
 * monochrome — that alternation is what keeps the row from reading as a
 * decorative bar graphic.
 *
 * The mark is still drawn on a canvas, for the same reason as before: every
 * mark is a pure function of the timeline position, so a frame is ~20 hairlines
 * and a few rects with no layout and no per-frame per-element style writes, and
 * ?splashAt=<ms> stays usable as a still-frame QA hook.
 *
 * Timing is paced against the app, but never time-warped:
 * - the story always plays at 1x; speeding it up is what reads as choppy;
 * - once the plate is assembled and the page underneath is idle, the exit
 *   starts right away instead of sitting on the final frame;
 * - if the app is still loading, the overlay holds the assembled plate and
 *   leaves the moment the queries settle;
 * - HARD_CAP is the last resort so a hanging request cannot trap the user.
 *
 * The hand-off is a plain fade, because the cover is already the page's canvas
 * colour: content dissolves first, then the cover lifts, so the page's content
 * comes up out of the same paper instead of popping in at full contrast.
 */

const TL = {
  baseline: { start: 0, dur: 300 },
  /** First candle prints here; each next candle is candleGap behind it. */
  candles: 170,
  candleGap: 55,
  candleGrow: 290,
  /** The decision rule crosses at the last close. */
  rule: { start: 800, dur: 180 },
  /** Square terminals print at both ends of both rules. */
  terminals: { start: 980, dur: 80 },
  /** The verdict candle takes its ink last, so the plate is not all empty,
      all at once. */
  stamp: { start: 1010, dur: 200 },
  word: { start: 1010, dur: 300 },
  subtitle: { start: 1120, dur: 280 },
} as const;

/** Everything is assembled by here: the story is 1.42s, not 3.8s. */
const STORY_MS = 1420;
/** A single tick of hold before anything moves: just enough for the page behind
    to be rasterised. Longer than this is a visible freeze, not a smooth beat. */
const PRIME_MS = 60;
/** The plate dissolves over this window, cover still solid. */
const FADE_MS = 240;
/** Then the cover itself lifts, revealing a page of the same paper. */
const REVEAL_MS = 220;
/** The plate is assembled by now, so the overlay may leave — but only once the
    route component underneath has actually mounted. Revealing while the route
    chunk is still loading hands the user the page's heaviest frame. */
const EARLY_EXIT_AT = STORY_MS;
/** Even a slow route may not hold the splash past this. */
const FORCE_EXIT_AT = 2100;
/** Once every query has settled, the page still needs a beat to do its one
    expensive render (charts, tables). Revealing on the same frame as that render
    is what read as a stutter, so the overlay waits this long after idle. */
const IDLE_SETTLE_MS = 240;
/** Longest the overlay may stay on screen, story included. */
const HARD_CAP_MS = 3000;

/** True once the routed page has replaced its Suspense skeleton, i.e. the
    heaviest first render of the app is already behind the overlay. */
function pageMounted(): boolean {
  if (typeof document === "undefined") {
    return true;
  }
  return !document.querySelector('[data-testid="route-fallback"]');
}

/* Plate geometry, in viewBox units (240 x 140). A wide, low chart: it reads as
   a printed plate on the page, where a tall mark read as a poster. */
const VIEW_W = 240;
const VIEW_H = 132;
const LEFT = 14;
const RIGHT = 226;
const BASE_Y = 124;
const BODY_W = 14;
/** Body plus the gap between candles: 26 units, so seven of them fill the plate
    without ever touching. */
const PITCH = 26;

/** Values are heights above the baseline. One candle per analyst, in the order
    the pipeline runs; the last one breaks above the decision rule. */
const SERIES = [
  { open: 18, close: 34, low: 12, high: 40 },
  { open: 34, close: 30, low: 22, high: 44 },
  { open: 30, close: 52, low: 24, high: 58 },
  { open: 52, close: 46, low: 38, high: 60 },
  { open: 46, close: 66, low: 40, high: 72 },
  { open: 66, close: 60, low: 52, high: 76 },
  { open: 60, close: 96, low: 54, high: 104 },
] as const;

const CANDLES = SERIES.map((candle, index) => ({
  ...candle,
  /** Higher of open/close: the top edge of the body. */
  bodyTop: Math.max(candle.open, candle.close),
  /** Lower of open/close: the bottom edge of the body. */
  bodyBottom: Math.min(candle.open, candle.close),
  /** A candle that closed lower than it opened is printed solid. */
  filled: candle.close < candle.open,
  cx:
    (VIEW_W - (BODY_W + PITCH * (SERIES.length - 1))) / 2 +
    index * PITCH +
    BODY_W / 2,
}));

/** Axis ticks under each candle, as a percentage of the canvas width: 01–07,
    one per analyst, so the row is counted rather than inferred. */
const TICK_LEFT = CANDLES.map((candle) => (candle.cx / VIEW_W) * 100);
const TICKS = CANDLES.map((_, index) => String(index + 1).padStart(2, "0"));

/** The decision rule sits on the last close: 96 above the baseline. */
const RULE_Y = BASE_Y - CANDLES[CANDLES.length - 1].close;
/** The last candle is the verdict, and the only body that gets washed with ink. */
const VERDICT = CANDLES.length - 1;

function clamp(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

function seg(t: number, start: number, duration: number): number {
  if (duration <= 0) {
    return t >= start ? 1 : 0;
  }
  return clamp((t - start) / duration);
}

function outCubic(p: number): number {
  return 1 - Math.pow(1 - p, 3);
}

/** Eased progress of a beat defined as { start, dur }, so no call site has to
    remember which half of a pair is the start. */
function beat(t: number, span: { start: number; dur: number }): number {
  return outCubic(seg(t, span.start, span.dur));
}

function preloadDisabled(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    return new URLSearchParams(window.location.search).get("splash") === "0";
  } catch {
    return false;
  }
}

function reducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * The shell applies the stored theme in an effect, which can land after this
 * overlay's first paint. Priming it at import keeps the paper from flashing the
 * other theme's colour on the way in. Only an explicit choice is applied — with
 * none, the media query in tokens.css already picks the right paper.
 */
function primeTheme(): void {
  if (typeof document === "undefined") {
    return;
  }
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("theme");
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    const theme = fromUrl === "dark" || fromUrl === "light" ? fromUrl : stored;
    if (theme === "dark" || theme === "light") {
      document.documentElement.dataset.theme = theme;
    }
  } catch {
    // Storage can be blocked (private mode); the media query default still applies.
  }
}

primeTheme();

export interface SplashProps {
  /** Called once the overlay has left the screen. */
  onDone?: () => void;
}

export function Splash({ onDone }: SplashProps = {}) {
  const [gone, setGone] = useState(preloadDisabled);
  const fetching = useIsFetching();

  const overlayRef = useRef<HTMLDivElement | null>(null);
  const markRef = useRef<HTMLCanvasElement | null>(null);
  const wordRef = useRef<HTMLDivElement | null>(null);
  const subtitleRef = useRef<HTMLDivElement | null>(null);
  const tickRefs = useRef<Array<HTMLSpanElement | null>>([]);

  /** Read by the animation loop, written by the query observer. */
  const idleRef = useRef(fetching === 0);

  useEffect(() => {
    idleRef.current = fetching === 0;
  }, [fetching]);

  useEffect(() => {
    if (preloadDisabled()) {
      onDone?.();
      return;
    }

    const overlay = overlayRef.current;
    if (!overlay) {
      return;
    }
    // Bound once so the hoisted `draw` below always sees a non-null element.
    const host: HTMLDivElement = overlay;

    let raf = 0;
    let t = 0;
    let elapsed = 0;
    let last = 0;
    /** When the exit fade begins; null while the overlay is still holding. */
    let exitAt: number | null = null;
    /** Timeline position at which every query last went quiet. */
    let idleSince: number | null = null;
    /** Whether the overlay has been promoted for its fade. */
    let primed = false;
    /** Opt-in hand-off diagnostics; also a readout on the canvas. */
    const debug =
      new URLSearchParams(window.location.search).get("splashDebug") === "1";
    let worstFrame = 0;
    /** Timeline position of the worst frame, so a stall can be located. */
    let worstAt = 0;
    /** Worst frame of the hand-off phase alone (prime → dissolve → reveal). */
    let worstExit = 0;
    let worstExitAt = 0;
    /** Frames drawn, for a rough fps sanity check. */
    let frames = 0;
    let finished = false;

    const canvas = markRef.current;
    const ctx = canvas ? canvas.getContext("2d") : null;
    // Ink is the ordinary text colour: on this overlay the paper is the page.
    const ink =
      getComputedStyle(overlay).getPropertyValue("--color-text-primary").trim() ||
      "black";

    /** Everything the eye reads as "the splash": dissolved as one unit before
        the cover itself lifts. */
    const candidates: Array<HTMLElement | null> = [
      canvas,
      wordRef.current,
      subtitleRef.current,
      ...tickRefs.current,
    ];
    const contentEls = candidates.filter(
      (element): element is HTMLElement => element instanceof HTMLElement,
    );

    let cssW = VIEW_W;
    let cssH = VIEW_H;
    let scale = 1;
    let dpr = 1;
    /** Last frame handed to the canvas, so a resize can repaint it immediately. */
    let drawnAt: number | null = null;

    /** Resizing is the only layout read; the frame loop never touches the DOM
        for geometry. */
    const resize = () => {
      if (!canvas) {
        return;
      }
      const width = canvas.clientWidth || VIEW_W;
      cssW = width;
      cssH = (width * VIEW_H) / VIEW_W;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      scale = width / VIEW_W;
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
      canvas.style.height = `${cssH}px`;
      // The first pass can run before layout settles, and a resized backing store
      // is blank: repaint whatever frame is currently on screen.
      if (drawnAt !== null) {
        draw(drawnAt);
      }
    };
    resize();

    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver === "function" && canvas) {
      observer = new ResizeObserver(resize);
      observer.observe(canvas);
    }

    /** Horizontal hairline, snapped to the pixel grid so it stays 1px crisp at
        any device pixel ratio. */
    const hline = (x0: number, y: number, x1: number, alpha: number) => {
      if (!ctx || alpha <= 0.01 || x1 - x0 < 0.5) {
        return;
      }
      const py = Math.round(y) + 0.5;
      ctx.globalAlpha = alpha;
      ctx.lineWidth = 1;
      ctx.strokeStyle = ink;
      ctx.beginPath();
      ctx.moveTo(Math.round(x0), py);
      ctx.lineTo(Math.round(x1), py);
      ctx.stroke();
      ctx.globalAlpha = 1;
    };

    /** Vertical hairline, same snapping. */
    const vline = (x: number, y0: number, y1: number, alpha: number) => {
      if (!ctx || alpha <= 0.01 || y0 - y1 < 0.5) {
        return;
      }
      const px = Math.round(x) + 0.5;
      ctx.globalAlpha = alpha;
      ctx.lineWidth = 1;
      ctx.strokeStyle = ink;
      ctx.beginPath();
      ctx.moveTo(px, Math.round(y0));
      ctx.lineTo(px, Math.round(y1));
      ctx.stroke();
      ctx.globalAlpha = 1;
    };

    const finish = () => {
      if (finished) {
        return;
      }
      finished = true;
      cancelAnimationFrame(raf);
      // The page is already showing in the same paper colour, so removing the
      // cover changes no visible pixel.
      host.style.opacity = "0";
      host.style.pointerEvents = "none";
      host.style.willChange = "auto";
      if (debug && typeof document !== "undefined") {
        // Outlives the overlay: the hand-off frames are the ones worth measuring,
        // and they happen right before the cover disappears.
        const readout = document.createElement("div");
        readout.className = styles.readout;
        const summary =
          `worst ${Math.round(worstFrame)}ms @${Math.round(worstAt)} · ` +
          `exit ${Math.round(worstExit)}ms @${Math.round(worstExitAt)} · ${frames}f`;
        readout.textContent = summary;
        document.body.appendChild(readout);
        window.setTimeout(() => readout.remove(), 15000);
        // Keep sampling for a moment after the cover is gone: if the app itself
        // stalls on its own first frames, that is not something this overlay can
        // fix, and it is worth telling apart from the hand-off.
        let worstPage = 0;
        let pageAt = 0;
        let prev = performance.now();
        const started = prev;
        const probe = (now: number) => {
          const gap = now - prev;
          prev = now;
          if (gap > worstPage) {
            worstPage = gap;
            pageAt = now - started;
          }
          if (now - started < 1400) {
            requestAnimationFrame(probe);
          } else {
            readout.textContent =
              `${summary} · page ${Math.round(worstPage)}ms @${Math.round(pageAt)}`;
          }
        };
        requestAnimationFrame(probe);
      }
      // Drop the full-screen layer one frame later: the page is already painted
      // underneath, so teardown never shares a frame with the app's first paint.
      raf = requestAnimationFrame(() => {
        setGone(true);
        onDone?.();
      });
    };

    function draw(time: number) {
      drawnAt = time;
      if (ctx) {
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, cssW, cssH);
      }
      // Reset before the exit multiplies it, or the fade would compound.
      if (canvas) {
        canvas.style.opacity = "1";
      }

      const s = scale;

      // 1. The baseline is ruled in from the left.
      const base = beat(time, TL.baseline);
      if (base > 0) {
        hline(LEFT * s, BASE_Y * s, (LEFT + (RIGHT - LEFT) * base) * s, 0.34);
      }

      // 2. Candles print one after another, rising out of the baseline: the wick
      //    grows first and the body follows it up, so each candle looks drawn
      //    rather than faded in.
      const stamp = beat(time, TL.stamp);
      CANDLES.forEach((candle, index) => {
        const grow = outCubic(
          seg(time, TL.candles + index * TL.candleGap, TL.candleGrow),
        );
        if (grow <= 0) {
          return;
        }
        const cx = candle.cx * s;
        const low = (BASE_Y - candle.low) * s;
        const high = (BASE_Y - candle.high) * s;
        const bodyTop = (BASE_Y - candle.bodyTop) * s;
        const bodyBottom = (BASE_Y - candle.bodyBottom) * s;
        const reach = low - (low - high) * grow;
        const halfW = (BODY_W * s) / 2;

        // The wick is split around the body, not drawn through it: a hairline
        // crossing a hollow body reads as a mistake at this size.
        vline(cx, low, Math.min(bodyBottom, reach), 0.72);
        if (reach < bodyTop) {
          vline(cx, bodyTop, reach, 0.72);
        }

        // The body is revealed up to wherever the wick has reached.
        const top = Math.max(bodyTop, reach);
        if (top >= bodyBottom) {
          return;
        }
        // Every body is outlined first. A hollow body is a candle that closed up,
        // and the outline is the whole mark; a filled body then covers it.
        const edge = 0.9 * (0.45 + 0.55 * grow);
        vline(cx - halfW, bodyBottom, top, edge);
        vline(cx + halfW, bodyBottom, top, edge);
        hline(cx - halfW, top, cx + halfW, 0.9);
        hline(cx - halfW, bodyBottom, cx + halfW, 0.9);

        // No context means a renderer that cannot rasterise (tests): the outline
        // helpers already no-op, and the fills below are skipped.
        if (!ctx) {
          return;
        }
        // Down candles print solid; the verdict candle is outlined like the rest
        // but takes full ink last, so the plate ends on one heavy mark.
        const filled = candle.filled || index === VERDICT;
        if (!filled) {
          return;
        }
        ctx.globalAlpha = index === VERDICT && !candle.filled ? 0.9 * stamp : 0.9;
        if (ctx.globalAlpha <= 0.01) {
          ctx.globalAlpha = 1;
          return;
        }
        ctx.fillStyle = ink;
        ctx.fillRect(cx - halfW, top, halfW * 2, bodyBottom - top);
        ctx.globalAlpha = 1;
      });

      // 3. Axis ticks: each number prints with its own candle, faint enough to
      //    read as a scale rather than a caption.
      tickRefs.current.forEach((element, index) => {
        if (!element) {
          return;
        }
        const appear = outCubic(
          seg(time, TL.candles + index * TL.candleGap + TL.candleGrow * 0.55, 200),
        );
        element.style.opacity = (0.6 * appear).toFixed(3);
      });

      // 4. The decision rule crosses at the level the last candle closed, so the
      //    final wick beyond it reads as a break rather than a decoration.
      const rule = beat(time, TL.rule);
      if (rule > 0) {
        hline(LEFT * s, RULE_Y * s, (LEFT + (RIGHT - LEFT) * rule) * s, 0.62);
      }

      // 5. Both rules get square terminals, the way a print proof marks its
      //    corners: it closes the plate without drawing a box around it.
      const terminals = beat(time, TL.terminals);
      if (ctx && terminals > 0) {
        const size = Math.max(1, 3.5 * terminals * s);
        ctx.globalAlpha = 0.9;
        ctx.fillStyle = ink;
        const corners: Array<readonly [number, number]> = [
          [LEFT, RULE_Y],
          [RIGHT, RULE_Y],
          [LEFT, BASE_Y],
          [RIGHT, BASE_Y],
        ];
        for (const [x, y] of corners) {
          ctx.fillRect(x * s - size / 2, y * s - size / 2, size, size);
        }
        ctx.globalAlpha = 1;
      }

      // 6. The wordmark locks up: opacity and a short rise, nothing that reflows
      //    text (animated tracking would relayout every frame).
      const word = beat(time, TL.word);
      if (wordRef.current) {
        wordRef.current.style.opacity = word.toFixed(3);
        wordRef.current.style.transform = `translateY(${((1 - word) * 9).toFixed(2)}px)`;
      }

      const subtitle = beat(time, TL.subtitle);
      if (subtitleRef.current) {
        subtitleRef.current.style.opacity = (0.9 * subtitle).toFixed(3);
        subtitleRef.current.style.transform =
          `translateY(${((1 - subtitle) * 5).toFixed(2)}px)`;
      }

      if (debug && ctx) {
        // QA readout (?splashDebug=1): worst frame since the story started.
        ctx.globalAlpha = 0.45;
        ctx.font = "11px ui-monospace, monospace";
        ctx.textAlign = "right";
        ctx.fillStyle = ink;
        ctx.fillText(
          `worst ${Math.round(worstFrame)}ms @${Math.round(worstAt)}`,
          cssW - 10,
          cssH - 12,
        );
        ctx.globalAlpha = 1;
        ctx.textAlign = "left";
      }

      // The hand-off: the plate dissolves first, cover still solid; then the
      // cover lifts. Because the cover is the page's own canvas colour, lifting
      // it does not change the paper — only the page's content comes up.
      if (exitAt === null) {
        host.style.opacity = "1";
      } else {
        const p = time - exitAt;
        if (!primed) {
          // 0.999 instead of 1: a fully opaque full-screen layer lets Chrome
          // skip rasterising the page beneath, which would charge that paint to
          // the frame where the cover finally lifts. 0.1% of the page bleeding
          // through is invisible, and it buys an already-rasterised page.
          host.style.opacity = "0.9990";
          host.style.willChange = "opacity";
          primed = true;
        }
        const fade = clamp((p - PRIME_MS) / FADE_MS);
        const content = 1 - outCubic(fade);
        contentEls.forEach((element) => {
          // Multiply, never overwrite: each layer keeps the level its own beat
          // gave it this frame. Writing the fade straight in would make beats
          // that have not started yet (the wordmark arrives at 1010ms) flash at
          // full strength just because the exit began.
          element.style.opacity = (Number(element.style.opacity || 1) * content).toFixed(3);
        });
        const reveal = outCubic(clamp((p - PRIME_MS - FADE_MS) / REVEAL_MS));
        if (reveal > 0) {
          host.style.opacity = (1 - reveal).toFixed(3);
        }
        host.style.pointerEvents = reveal > 0.99 ? "none" : "auto";
      }
    }

    const frame = (now: number) => {
      if (!last) {
        last = now;
      }
      // The raw gap is what the eye sees; the clamped value only keeps a
      // background-tab pause from teleporting the story.
      const raw = now - last;
      const delta = Math.min(raw, 64);
      last = now;
      elapsed += delta;

      t += delta;
      frames += 1;
      // Ignore tab-hide gaps: they are not frames the user ever saw.
      if (debug && raw > worstFrame && raw < 500) {
        worstFrame = raw;
        worstAt = t;
      }
      if (debug && exitAt !== null && raw > worstExit && raw < 500) {
        worstExit = raw;
        worstExitAt = t;
      }

      if (idleRef.current) {
        if (idleSince === null) {
          idleSince = t;
        }
      } else {
        idleSince = null;
      }

      if (exitAt === null) {
        // Three hand-off conditions: the plate has assembled, the page under the
        // overlay has mounted, and its data has been quiet long enough that the
        // expensive render is already done and hidden.
        const settled = idleSince !== null && t - idleSince >= IDLE_SETTLE_MS;
        const canLeave = t >= EARLY_EXIT_AT && pageMounted() && settled;
        if (canLeave || t >= FORCE_EXIT_AT) {
          exitAt = Math.max(t, EARLY_EXIT_AT);
        }
      }

      const exitDone =
        exitAt !== null && t >= exitAt + PRIME_MS + FADE_MS + REVEAL_MS;
      if (elapsed > HARD_CAP_MS || exitDone) {
        draw(
          exitAt === null
            ? Math.min(t, STORY_MS)
            : Math.min(t, STORY_MS + PRIME_MS + FADE_MS + REVEAL_MS),
        );
        finish();
        return;
      }

      draw(exitAt === null ? Math.min(t, STORY_MS) : t);
      raf = requestAnimationFrame(frame);
    };

    // Design QA hook: ?splashAt=<ms> freezes the overlay on that timeline frame
    // so a still can be reviewed without chasing the animation.
    const frozenAt = Number(new URLSearchParams(window.location.search).get("splashAt"));
    if (Number.isFinite(frozenAt) && frozenAt > 0) {
      draw(Math.min(frozenAt, STORY_MS));
      overlay.style.opacity = "1";
      return () => {
        observer?.disconnect();
      };
    }

    if (reducedMotion()) {
      draw(STORY_MS);
      overlay.style.opacity = "1";
      const timer = window.setTimeout(finish, 260);
      return () => {
        window.clearTimeout(timer);
        cancelAnimationFrame(raf);
        observer?.disconnect();
      };
    }

    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      observer?.disconnect();
    };
  }, [onDone]);

  if (gone) {
    return null;
  }

  return (
    <div className={styles.overlay} ref={overlayRef} aria-hidden="true" data-testid="splash-overlay">
      <div className={styles.stage}>
        <div className={styles.plot}>
          <canvas
            className={styles.mark}
            ref={markRef}
            width={VIEW_W}
            height={VIEW_H}
            aria-hidden="true"
          />

          <div className={styles.ticks}>
            {TICKS.map((tick, index) => (
              <span
                className={styles.tick}
                key={tick}
                style={{ left: `${TICK_LEFT[index]}%`, opacity: 0 }}
                ref={(element) => {
                  tickRefs.current[index] = element;
                }}
              >
                {tick}
              </span>
            ))}
          </div>
        </div>

        <div className={styles.wordmark} ref={wordRef} style={{ opacity: 0 }}>
          ASTOCK PRO
        </div>
        <div className={styles.subtitle} ref={subtitleRef} style={{ opacity: 0 }}>
          多智能体投研引擎
        </div>
      </div>
    </div>
  );
}
