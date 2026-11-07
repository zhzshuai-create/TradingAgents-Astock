/** Local waiting state after the user starts the journal themselves. */

import { Button } from "../../ui";
import styles from "./JournalPage.module.css";

export interface JournalStartingProps {
  elapsedSeconds: number;
  entryUrl: string | null;
  onCancel: () => void;
}

export function JournalStarting({
  elapsedSeconds,
  entryUrl,
  onCancel,
}: JournalStartingProps) {
  return (
    <>
      <p className={styles.lead} role="status">
        正在等待日志服务就绪…
      </p>

      <div className={styles.reasonBlock} data-state="starting">
        <p className={styles.note}>
          已等待 {elapsedSeconds} 秒，最多等待 30 秒；期间每 2 秒重新检测一次。
        </p>
        {entryUrl === null || entryUrl === "" ? null : (
          <p className={styles.note}>
            入口地址：<code className={styles.code}>{entryUrl}</code>
          </p>
        )}
        <div className={styles.actions}>
          <Button variant="secondary" onClick={onCancel}>
            取消等待
          </Button>
        </div>
      </div>

      <p className={styles.isolation}>本系统不会读取或修改交易日志的数据。</p>
    </>
  );
}
