/** Display helpers shared by the W08 market blocks. */

export type ChangeTone = "up" | "down" | "flat";

export function changeTone(value: number | null): ChangeTone {
  if (value === null || value === 0) {
    return "flat";
  }
  return value > 0 ? "up" : "down";
}

export function formatPrice(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "—";
  }
  return value.toFixed(2);
}

export function formatSignedPct(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "—";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function formatPct(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "—";
  }
  return `${value.toFixed(2)}%`;
}

export function formatSignedAmount(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "—";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** "11-06 09:30"; unparsable or missing timestamps read as a dash. */
export function formatMarketTime(iso: string | null): string {
  if (iso === null) {
    return "—";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

/** Theme chips aggregate the free-form reason strings, most frequent first. */
export function topThemes(reasons: string[], limit = 8): string[] {
  const counts = new Map<string, number>();
  for (const raw of reasons) {
    const reason = raw.trim();
    if (reason === "") {
      continue;
    }
    counts.set(reason, (counts.get(reason) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, limit)
    .map(([reason]) => reason);
}