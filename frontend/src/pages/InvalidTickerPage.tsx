import { Link } from "react-router-dom";

import { SearchBox } from "../features/search/SearchBox";
import styles from "./pages.module.css";

/**
 * `format` covers non-6-digit paths; `unresolved` is the server's 400
 * `invalid_request` + `details.field="ticker"` (p4-backlog D10).
 */
export type InvalidTickerReason = "format" | "unresolved";

export interface InvalidTickerPageProps {
  ticker: string;
  reason?: InvalidTickerReason;
}

export function InvalidTickerPage({
  ticker,
  reason = "format",
}: InvalidTickerPageProps) {
  return (
    <section className={styles.page} data-testid="invalid-ticker">
      <p className={styles.kicker}>400</p>
      <h1 className={styles.title}>没有这只股票</h1>
      <p className={styles.lead}>
        股票代码
        {ticker ? <code className={styles.code}>{ticker}</code> : null}
        {reason === "unresolved"
          ? "不在本地名称表中。请重新输入，或回到市场重新选择。"
          : "不是 6 位数字。请重新输入，或回到市场重新选择。"}
      </p>
      <div className={styles.searchBox}>
        <SearchBox />
      </div>
      <div className={styles.actions}>
        <Link className={styles.textLink} to="/market">
          回市场
        </Link>
      </div>
    </section>
  );
}
