/** URL query <-> W08 market view state (p4-backlog W08-07). */

export const INDUSTRY_TOP_OPTIONS = [10, 20, 30] as const;
export type IndustryTop = (typeof INDUSTRY_TOP_OPTIONS)[number];
export const DEFAULT_INDUSTRY_TOP: IndustryTop = 20;
export const CONSTITUENT_LIMIT = 10;
export const NEWSFLASH_LIMIT = 30;

export interface MarketState {
  top: IndustryTop;
  /** "" means the provider's latest trading day. */
  date: string;
  /** "" means the constituent drawer is closed. */
  board: string;
  /** "" means every theme is shown. */
  theme: string;
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const BOARD_PATTERN = /^BK\d{4}$/;

export function isMarketDate(value: string): boolean {
  if (!DATE_PATTERN.test(value)) {
    return false;
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  return (
    !Number.isNaN(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}

function parseTop(raw: string | null): IndustryTop {
  const value = Number(raw);
  return (INDUSTRY_TOP_OPTIONS as readonly number[]).includes(value)
    ? (value as IndustryTop)
    : DEFAULT_INDUSTRY_TOP;
}

export function parseMarketSearch(search: string): MarketState {
  const params = new URLSearchParams(search);
  const date = (params.get("date") ?? "").trim();
  const board = (params.get("board") ?? "").trim().toUpperCase();
  return {
    top: parseTop(params.get("top")),
    date: isMarketDate(date) ? date : "",
    board: BOARD_PATTERN.test(board) ? board : "",
    theme: (params.get("theme") ?? "").trim().slice(0, 32),
  };
}

/** Canonical query without "?"; defaults and invalid values are dropped. */
export function toMarketSearch(state: MarketState): string {
  const params = new URLSearchParams();
  if (state.top !== DEFAULT_INDUSTRY_TOP) {
    params.set("top", String(state.top));
  }
  if (isMarketDate(state.date)) {
    params.set("date", state.date);
  }
  if (BOARD_PATTERN.test(state.board)) {
    params.set("board", state.board);
  }
  if (state.theme !== "") {
    params.set("theme", state.theme);
  }
  return params.toString();
}