export type IconName =
  | "workbench"
  | "market"
  | "jobs"
  | "reports"
  | "journal"
  | "settings"
  | "more"
  | "search"
  | "collapse"
  | "expand"
  | "sun"
  | "moon"
  | "external";

export interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  /** Route prefixes that keep this item highlighted. */
  matches: string[];
}

export const PRIMARY_NAV: NavItem[] = [
  {
    to: "/workbench",
    label: "工作台",
    icon: "workbench",
    matches: ["/workbench"],
  },
  {
    to: "/market",
    label: "市场",
    icon: "market",
    matches: ["/market", "/stocks"],
  },
  { to: "/jobs", label: "任务", icon: "jobs", matches: ["/jobs"] },
  {
    to: "/reports",
    label: "报告",
    icon: "reports",
    matches: ["/reports"],
  },
];

export const SECONDARY_NAV: NavItem[] = [
  { to: "/journal", label: "交易日志", icon: "journal", matches: ["/journal"] },
  { to: "/settings", label: "设置", icon: "settings", matches: ["/settings"] },
];

/** Legacy Streamlit entry stays the default write path until P2 ships. */
export const LEGACY_ENTRY_URL = "http://localhost:8501";

export function isNavActive(pathname: string, item: NavItem): boolean {
  return item.matches.some(
    (base) => pathname === base || pathname.startsWith(`${base}/`),
  );
}

export function pageTitle(pathname: string): string {
  const match = [...PRIMARY_NAV, ...SECONDARY_NAV].find((item) =>
    isNavActive(pathname, item),
  );
  return match?.label ?? "AStock Pro";
}
