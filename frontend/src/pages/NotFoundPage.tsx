import { Link } from "react-router-dom";

import styles from "./pages.module.css";

export function NotFoundPage() {
  return (
    <section className={styles.page} data-testid="not-found">
      <p className={styles.kicker}>404</p>
      <h1 className={styles.title}>页面不存在</h1>
      <p className={styles.lead}>
        链接可能已经失效，或者地址输入有误。你可以回到工作台，或查看任务列表。
      </p>
      <div className={styles.actions}>
        <Link className={styles.textLink} to="/workbench">
          回工作台
        </Link>
        <Link className={styles.textLink} to="/jobs">
          回任务列表
        </Link>
      </div>
    </section>
  );
}
