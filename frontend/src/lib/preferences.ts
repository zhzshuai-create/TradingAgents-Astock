/**
 * Non-sensitive UI preferences (p5-backlog D1). They live only in
 * ``localStorage``; nothing here is sent to the backend or merged into a job
 * config snapshot, so a change never touches an existing task.
 */

import { useSyncExternalStore } from "react";

export type Density = "comfortable" | "compact";
export type RefreshProfile = "standard" | "relaxed" | "manual";
export type ExportProfile = "pdf" | "markdown";

export interface LauncherDefaults {
  llm_profile?: string;
  parallel_analysts?: boolean;
}

export interface Preferences {
  density: Density;
  refresh: RefreshProfile;
  export: ExportProfile;
  launcher: LauncherDefaults;
}

export const PREFERENCES_STORAGE_KEY = "astock.prefs.v1";

const DENSITIES = ["comfortable", "compact"] as const;
const REFRESH_PROFILES = ["standard", "relaxed", "manual"] as const;
const EXPORT_PROFILES = ["pdf", "markdown"] as const;

export const DEFAULT_PREFERENCES: Preferences = Object.freeze({
  density: "comfortable",
  refresh: "standard",
  export: "pdf",
  launcher: Object.freeze({}),
});

function pick<T extends string>(
  allowed: readonly T[],
  value: unknown,
): T | null {
  return typeof value === "string" &&
    (allowed as readonly string[]).includes(value)
    ? (value as T)
    : null;
}

function normalizeLauncher(value: unknown): LauncherDefaults | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const source = value as Record<string, unknown>;
  const launcher: LauncherDefaults = {};
  if (typeof source.llm_profile === "string") {
    launcher.llm_profile = source.llm_profile;
  }
  if (typeof source.parallel_analysts === "boolean") {
    launcher.parallel_analysts = source.parallel_analysts;
  }
  return launcher;
}

function normalizePreferences(value: unknown): Preferences {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return DEFAULT_PREFERENCES;
  }
  const source = value as Record<string, unknown>;
  return {
    density: pick(DENSITIES, source.density) ?? DEFAULT_PREFERENCES.density,
    refresh: pick(REFRESH_PROFILES, source.refresh) ?? DEFAULT_PREFERENCES.refresh,
    export: pick(EXPORT_PROFILES, source.export) ?? DEFAULT_PREFERENCES.export,
    launcher: normalizeLauncher(source.launcher) ?? {},
  };
}

/** A merged object, kept in one place so the cache and storage agree. */
let cached: Preferences = DEFAULT_PREFERENCES;
let cachedRaw: string | null = null;
let hasCache = false;
/** Set when the last write failed: the in-memory value wins over storage. */
let memoryOnly = false;

const subscribers = new Set<() => void>();
let listening = false;

function readRaw(): string | null {
  try {
    return typeof localStorage === "undefined"
      ? null
      : localStorage.getItem(PREFERENCES_STORAGE_KEY);
  } catch {
    return null;
  }
}

function notify(): void {
  for (const subscriber of subscribers) {
    subscriber();
  }
}

function parseRaw(raw: string | null): Preferences {
  if (raw === null) {
    return DEFAULT_PREFERENCES;
  }
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return DEFAULT_PREFERENCES;
  }
  return normalizePreferences(value);
}

/**
 * Stable snapshot for ``useSyncExternalStore``: the parsed object is reused
 * while the stored string is unchanged, and a write that failed on quota keeps
 * the in-memory value instead of falling back to a stale entry.
 */
export function readPreferences(): Preferences {
  const raw = readRaw();
  if (hasCache && (memoryOnly || raw === cachedRaw)) {
    return cached;
  }
  hasCache = true;
  cachedRaw = raw;
  cached = parseRaw(raw);
  return cached;
}

function commit(next: Preferences): Preferences {
  const raw = JSON.stringify(next);
  cached = next;
  cachedRaw = raw;
  hasCache = true;
  try {
    localStorage.setItem(PREFERENCES_STORAGE_KEY, raw);
    memoryOnly = false;
  } catch {
    memoryOnly = true;
  }
  notify();
  return next;
}

function mergePreferences(
  current: Preferences,
  patch: Partial<Preferences>,
): Preferences {
  const source = patch as Record<string, unknown>;
  const launcher = normalizeLauncher(source.launcher);
  return {
    density: pick(DENSITIES, source.density) ?? current.density,
    refresh: pick(REFRESH_PROFILES, source.refresh) ?? current.refresh,
    export: pick(EXPORT_PROFILES, source.export) ?? current.export,
    launcher:
      launcher === null ? current.launcher : { ...current.launcher, ...launcher },
  };
}

/** Replace every field; unknown keys and bad values are dropped. */
export function writePreferences(preferences: Preferences): Preferences {
  return commit(normalizePreferences(preferences));
}

/** Merge a whitelisted patch, persist it and notify every subscriber once. */
export function setPreferences(patch: Partial<Preferences>): Preferences {
  return commit(mergePreferences(readPreferences(), patch));
}

function handleStorage(event: StorageEvent): void {
  if (event.key !== PREFERENCES_STORAGE_KEY) {
    return;
  }
  if (event.newValue === null) {
    cached = DEFAULT_PREFERENCES;
    cachedRaw = null;
    hasCache = true;
    memoryOnly = false;
    notify();
    return;
  }
  // A corrupt value from another tab never resets the current session.
  let value: unknown;
  try {
    value = JSON.parse(event.newValue);
  } catch {
    return;
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return;
  }
  cached = normalizePreferences(value);
  cachedRaw = event.newValue;
  hasCache = true;
  memoryOnly = false;
  notify();
}

export function subscribePreferences(callback: () => void): () => void {
  subscribers.add(callback);
  if (!listening && typeof window !== "undefined") {
    listening = true;
    window.addEventListener("storage", handleStorage);
  }
  return () => {
    subscribers.delete(callback);
    if (subscribers.size === 0 && listening && typeof window !== "undefined") {
      window.removeEventListener("storage", handleStorage);
      listening = false;
    }
  };
}

export function usePreferences(): Preferences {
  return useSyncExternalStore(
    subscribePreferences,
    readPreferences,
    () => DEFAULT_PREFERENCES,
  );
}
