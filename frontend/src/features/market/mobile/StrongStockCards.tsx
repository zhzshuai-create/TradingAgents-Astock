import { Link } from "react-router-dom";

import type { StrongStockItem } from "../../../api/types";
import {
  changeTone,
  formatPct,
  formatPrice,
  formatSignedPct,
} from "../format";
import { themeFilter, ThemeChips } from "../ThemeChips";
import styles from "../MarketPage.module.css";

export interface StrongStockCardsProps {
  items: StrongStockItem[];
  activeTheme: string;
  onThemeChange: (theme: string) => void;
}

const TONE_CLASS = {
  up: styles.up,
  down: styles.down,
  flat: styles.flat,
} as const;

export function StrongStockCards({
  items,
  activeTheme,
  onThemeChange,
}: StrongStockCardsProps) {
  const { themes, active, visible } = themeFilter(items, activeTheme);

  return (
    <div data-testid="strong-block">
      <ThemeChips themes={themes} active={active} onThemeChange={onThemeChange} />
      <div className={styles.strongCards} data-testid="strong-cards">
        {visible.map((item) => (
          <article
            key={item.ticker_code}
            className={styles.strongCard}
            data-testid="strong-card"
            data-ticker={item.ticker_code}
          >
            <Link
              className={styles.strongCardLink}
              to={`/stocks/${item.ticker_code}`}
            >
              <span className={styles.strongCardName}>{item.name}</span>
              <span className={styles.constituentCode}>{item.ticker_code}</span>
              <span
                className={`${styles.numeric} ${
                  TONE_CLASS[changeTone(item.change_pct)]
                }`}
              >
                {formatSignedPct(item.change_pct)}
              </span>
            </Link>
            <div className={styles.strongCardMeta}>
              <span className={styles.strongCardReason}>
                {item.reason || "—"}
              </span>
              <span>最新 {formatPrice(item.close)}</span>
              <span>换手 {formatPct(item.turnover_pct)}</span>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}