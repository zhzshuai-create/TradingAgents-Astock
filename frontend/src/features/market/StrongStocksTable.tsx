import { Link } from "react-router-dom";

import type { StrongStockItem } from "../../api/types";
import {
  changeTone,
  formatPct,
  formatPrice,
  formatSignedPct,
} from "./format";
import { themeFilter, ThemeChips } from "./ThemeChips";
import styles from "./MarketPage.module.css";

export interface StrongStocksTableProps {
  items: StrongStockItem[];
  activeTheme: string;
  onThemeChange: (theme: string) => void;
}

const TONE_CLASS = {
  up: styles.up,
  down: styles.down,
  flat: styles.flat,
} as const;

export function StrongStocksTable({
  items,
  activeTheme,
  onThemeChange,
}: StrongStocksTableProps) {
  const { themes, active, visible } = themeFilter(items, activeTheme);

  return (
    <div data-testid="strong-block">
      <ThemeChips themes={themes} active={active} onThemeChange={onThemeChange} />
      <div className={styles.tableScroll}>
        <table className={styles.table} data-testid="strong-table">
          <thead>
            <tr>
              <th scope="col">股票</th>
              <th scope="col">题材</th>
              <th scope="col" className={styles.numeric}>
                涨跌幅
              </th>
              <th scope="col" className={styles.numeric}>
                最新价
              </th>
              <th scope="col" className={styles.numeric}>
                换手率
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.map((item) => (
              <tr
                key={item.ticker_code}
                className={styles.industryRow}
                data-testid="strong-row"
                data-ticker={item.ticker_code}
              >
                <td>
                  <Link
                    className={styles.stockLink}
                    to={`/stocks/${item.ticker_code}`}
                  >
                    <span>{item.name}</span>
                    <span className={styles.constituentCode}>
                      {item.ticker_code}
                    </span>
                  </Link>
                </td>
                <td className={styles.reasonCell}>{item.reason || "—"}</td>
                <td
                  className={`${styles.numeric} ${
                    TONE_CLASS[changeTone(item.change_pct)]
                  }`}
                >
                  {formatSignedPct(item.change_pct)}
                </td>
                <td className={styles.numeric}>{formatPrice(item.close)}</td>
                <td className={styles.numeric}>{formatPct(item.turnover_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}