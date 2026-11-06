import type { StrongStockItem } from "../../api/types";
import { topThemes } from "./format";
import styles from "./MarketPage.module.css";

/** Themed view of one strong-stock list; a missing theme falls back to all. */
export function themeFilter(items: StrongStockItem[], activeTheme: string) {
  const themes = topThemes(items.map((item) => item.reason));
  const active = themes.includes(activeTheme) ? activeTheme : "";
  const visible =
    active === "" ? items : items.filter((item) => item.reason.trim() === active);
  return { themes, active, visible };
}

export interface ThemeChipsProps {
  themes: string[];
  active: string;
  onThemeChange: (theme: string) => void;
}

export function ThemeChips({ themes, active, onThemeChange }: ThemeChipsProps) {
  return (
    <div className={styles.themeChips} data-testid="theme-chips">
      <button
        type="button"
        className={styles.themeChip}
        aria-pressed={active === ""}
        data-testid="theme-chip"
        onClick={() => onThemeChange("")}
      >
        全部
      </button>
      {themes.map((theme) => (
        <button
          key={theme}
          type="button"
          className={styles.themeChip}
          aria-pressed={active === theme}
          data-testid="theme-chip"
          onClick={() => onThemeChange(theme === active ? "" : theme)}
        >
          {theme}
        </button>
      ))}
    </div>
  );
}