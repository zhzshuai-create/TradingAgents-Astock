import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Splash } from "./Splash";

/*
 * The overlay is paced against the app rather than a fixed clock, so the three
 * things worth pinning are:
 * - the story is short (1.42s) and complete at the end — a splash that names the
 *   product has to actually show the name;
 * - a fast app must not sit through the whole story, and the hand-off must
 *   dissolve the plate before it lifts the cover;
 * - a slow app must not be trapped (HARD_CAP releases the overlay).
 *
 * The candles live on the canvas, which jsdom cannot rasterise, so the beats are
 * pinned through the DOM layers only. Stills of the plate come from
 * ?splashAt=<ms> in a real browser.
 */

let clock = 0;
let frames: FrameRequestCallback[] = [];

function advance(ms: number, step = 16): void {
  let elapsed = 0;
  while (elapsed < ms) {
    clock += step;
    elapsed += step;
    const due = frames;
    frames = [];
    due.forEach((callback) => {
      callback(clock);
    });
  }
}

function renderSplash(options: { pending?: boolean } = {}): {
  onDone: ReturnType<typeof vi.fn>;
} {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  if (options.pending) {
    // A query that never settles: the app is still loading.
    client.setQueryDefaults(["boot"], { queryFn: () => new Promise(() => {}) });
    void client.prefetchQuery({ queryKey: ["boot"] });
  }

  const onDone = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <Splash onDone={onDone} />
    </QueryClientProvider>,
  );
  return { onDone };
}

beforeEach(() => {
  clock = 0;
  frames = [];
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.push(callback);
    return frames.length;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {});
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("启动遮罩的时间适配", () => {
  it("叙事在 1.42s 内讲完，字标已经落定", () => {
    const { onDone } = renderSplash();

    act(() => { advance(1400); });

    expect(onDone).not.toHaveBeenCalled();
    expect(Number(screen.getByText("ASTOCK PRO").style.opacity)).toBeGreaterThan(0.95);
    expect(screen.getByText("多智能体投研引擎")).toBeInTheDocument();
  });

  it("应用已就绪时提前收尾，不等满整段故事", () => {
    const { onDone } = renderSplash();
    expect(screen.getByText("ASTOCK PRO")).toBeInTheDocument();

    // Exit starts once the plate is assembled (1420ms), then 60ms of hold,
    // 240ms of dissolve and 220ms of cover reveal.
    act(() => { advance(2400); });

    expect(onDone).toHaveBeenCalled();
    expect(screen.queryByText("ASTOCK PRO")).not.toBeInTheDocument();
  });

  it("退场先把画面收掉，遮罩本身最后才淡出", () => {
    renderSplash();

    // 1650ms sits inside the dissolve: the plate is nearly gone, the cover is
    // still solid, so the page underneath is not double-exposed.
    act(() => { advance(1650); });

    const overlay = screen.getByTestId("splash-overlay");
    expect(Number(overlay.style.opacity)).toBeGreaterThan(0.99);
    expect(Number(overlay.style.opacity)).toBeLessThan(1);
    expect(Number(screen.getByText("ASTOCK PRO").style.opacity)).toBeLessThan(0.05);
  });

  it("遮罩就是页面本色，不需要中间换色的纱幕", () => {
    renderSplash();

    expect(screen.queryByTestId("splash-veil")).toBeNull();
  });

  it("应用仍在加载时停在稳态画面，不会提前消失", () => {
    const { onDone } = renderSplash({ pending: true });

    act(() => { advance(2000); });

    expect(onDone).not.toHaveBeenCalled();
    expect(screen.getByTestId("splash-overlay").style.opacity).toBe("1");
    expect(screen.getByText("ASTOCK PRO")).toBeInTheDocument();
  });

  it("最长 3s 释放，挂起的请求也不会把用户锁住", () => {
    const { onDone } = renderSplash({ pending: true });

    act(() => { advance(3600); });

    expect(onDone).toHaveBeenCalled();
    expect(screen.queryByText("ASTOCK PRO")).not.toBeInTheDocument();
  });

  it("七根 K 线各自带一个 01–07 的刻度编号", () => {
    renderSplash();

    for (const tick of ["01", "02", "03", "04", "05", "06", "07"]) {
      expect(screen.getByText(tick)).toBeInTheDocument();
    }
    expect(screen.queryByText("08")).toBeNull();
  });

  it("不再出现版本号和角落里的技术标签", () => {
    renderSplash();

    expect(screen.queryByText(/v0\.2\.\d+/)).toBeNull();
    expect(screen.queryByText(/127\.0\.0\.1/)).toBeNull();
    expect(screen.queryByText(/LANGGRAPH/i)).toBeNull();
  });
});
