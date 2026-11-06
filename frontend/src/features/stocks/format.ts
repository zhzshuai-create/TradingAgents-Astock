/** Display helpers for the W07 stock workspace. */

export const DASH = "—";

export function formatNumber(
  value: number | null | undefined,
  digits = 2,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return DASH;
  }
  return value.toFixed(digits);
}

export function formatMoney(
  value: number | null | undefined,
  unit: string,
): string {
  const text = formatNumber(value);
  return text === DASH ? DASH : `${text} ${unit}`;
}

/** A-share convention: red up, green down, muted flat. */
export function toneOf(value: number | null | undefined): "up" | "down" | "flat" {
  if (value === null || value === undefined || !Number.isFinite(value) || value === 0) {
    return "flat";
  }
  return value > 0 ? "up" : "down";
}
