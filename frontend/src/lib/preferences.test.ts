import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Preferences } from "./preferences";

const KEY = "astock.prefs.v1";
const DEFAULTS: Preferences = {
  density: "comfortable",
  refresh: "standard",
  export: "pdf",
  launcher: {},
};

/** Each case starts from a fresh module so the snapshot cache is empty. */
async function load() {
  vi.resetModules();
  return import("./preferences");
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("PREF-01 容错读取", () => {
  it("空存储返回四个默认值", async () => {
    const { readPreferences, DEFAULT_PREFERENCES } = await load();
    expect(readPreferences()).toEqual(DEFAULTS);
    expect(readPreferences()).toBe(DEFAULT_PREFERENCES);
  });

  it.each([
    ["非法 JSON", "{oops"],
    [
      "越界枚举",
      JSON.stringify({ density: "cozy", refresh: "fast", export: "docx" }),
    ],
    ["非对象", JSON.stringify([1, 2, 3])],
    ["null", "null"],
  ])("%s 回默认", async (_label, raw) => {
    localStorage.setItem(KEY, raw);
    const { readPreferences } = await load();
    expect(readPreferences()).toEqual(DEFAULTS);
  });

  it("部分字段越界只回退该字段", async () => {
    localStorage.setItem(
      KEY,
      JSON.stringify({ density: "compact", refresh: "fast", export: "markdown" }),
    );
    const { readPreferences } = await load();
    expect(readPreferences()).toEqual({
      density: "compact",
      refresh: "standard",
      export: "markdown",
      launcher: {},
    });
  });
});

describe("PREF-02 白名单合并与订阅", () => {
  it("只合并白名单字段、丢弃未知键并通知一次", async () => {
    const { readPreferences, setPreferences, subscribePreferences } = await load();
    const listener = vi.fn();
    const unsubscribe = subscribePreferences(listener);

    const next = setPreferences({ density: "compact", refresh: "manual" });
    expect(next).toEqual({ ...DEFAULTS, density: "compact", refresh: "manual" });
    expect(JSON.parse(localStorage.getItem(KEY) ?? "null")).toEqual(next);
    expect(listener).toHaveBeenCalledTimes(1);

    setPreferences({
      density: "comfortable",
      api_key: "sk-test",
      base_url: "http://example.invalid",
    } as unknown as Partial<Preferences>);

    const stored = localStorage.getItem(KEY) ?? "";
    expect(stored).not.toContain("sk-test");
    expect(stored).not.toContain("base_url");
    expect(readPreferences().refresh).toBe("manual");
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
  });

  it("合并 launcher 时保留已有键并丢弃非法值", async () => {
    const { readPreferences, setPreferences } = await load();

    setPreferences({ launcher: { llm_profile: "fast", parallel_analysts: true } });
    setPreferences({ launcher: { parallel_analysts: false } });
    expect(readPreferences().launcher).toEqual({
      llm_profile: "fast",
      parallel_analysts: false,
    });

    setPreferences({
      launcher: { llm_profile: 7, unknown: "x" },
    } as unknown as Partial<Preferences>);
    expect(readPreferences().launcher).toEqual({
      llm_profile: "fast",
      parallel_analysts: false,
    });
  });
});

describe("PREF-03 存储异常", () => {
  it("getItem 抛异常时读取回默认", async () => {
    const { readPreferences } = await load();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    expect(readPreferences()).toEqual(DEFAULTS);
  });

  it("setItem 抛异常时不抛，内存值仍生效", async () => {
    const { readPreferences, setPreferences } = await load();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });

    expect(() =>
      setPreferences({ density: "compact", refresh: "relaxed" }),
    ).not.toThrow();
    expect(readPreferences()).toMatchObject({
      density: "compact",
      refresh: "relaxed",
    });
    expect(localStorage.getItem(KEY)).toBeNull();
  });
});

describe("PREF-04 跨标签页同步", () => {
  it("storage 事件只接受本键与合法值", async () => {
    const { readPreferences, subscribePreferences } = await load();
    const listener = vi.fn();
    const unsubscribe = subscribePreferences(listener);

    window.dispatchEvent(
      new StorageEvent("storage", { key: "astock.theme", newValue: "dark" }),
    );
    expect(listener).not.toHaveBeenCalled();
    expect(readPreferences().density).toBe("comfortable");

    window.dispatchEvent(
      new StorageEvent("storage", { key: KEY, newValue: "{oops" }),
    );
    expect(listener).not.toHaveBeenCalled();
    expect(readPreferences().density).toBe("comfortable");

    const raw = JSON.stringify({ density: "compact" });
    localStorage.setItem(KEY, raw);
    window.dispatchEvent(
      new StorageEvent("storage", { key: KEY, newValue: raw }),
    );
    expect(listener).toHaveBeenCalledTimes(1);
    expect(readPreferences()).toEqual({ ...DEFAULTS, density: "compact" });

    unsubscribe();
  });
});
