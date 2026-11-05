import { Link } from "react-router-dom";

import { SearchSlot } from "../shell/SearchSlot";
import styles from "./pages.module.css";

export function InvalidTickerPage({ ticker }: { ticker: string }) {
  return (
    <section className={styles.page} data-testid="invalid-ticker">
      <p className={styles.kicker}>400</p>
      <h1 className={styles.title}>没有这只股票</h1>
      <p className={styles.lead}>
        股票代码
        {ticker ? <code className={styles.code}>{ticker}</code> : null}
        不是 6 位数字。请重新输入，或回到市场重新选择。
      </p>
      <div className={styles.searchBox}>
        <SearchSlot />
      </div>
      <div className={styles.actions}>
        <Link className={styles.textLink} to="/market">
          回市场
        </Link>
      </div>
    </section>
  );
}
