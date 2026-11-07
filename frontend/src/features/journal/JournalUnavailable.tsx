/** Unavailable state: one lead sentence, one reason branch, one honest next step. */

import type { JournalReason } from "../../api/types";
import { Button } from "../../ui";
import styles from "./JournalPage.module.css";

const REASON_TITLE: Record<JournalReason, string> = {
  not_running: "日志服务当前没有在运行",
  not_installed: "还没有安装交易日志",
  probe_failed: "暂时无法确认日志服务状态",
};

export interface JournalUnavailableProps {
  reason: JournalReason | null;
  entryUrl: string | null;
  onRetry: () => void;
}

export function JournalUnavailable({
  reason,
  entryUrl,
  onRetry,
}: JournalUnavailableProps) {
  const branch: JournalReason = reason ?? "probe_failed";

  return (
    <>
      <p className={styles.lead} role="status" aria-live="polite">
        交易日志是独立应用，当前没有在运行。
      </p>

      <div className={styles.reasonBlock} data-reason={branch}>
        <p className={styles.reasonTitle}>{REASON_TITLE[branch]}</p>

        {branch === "not_running" ? (
          <>
            <p className={styles.note}>
              在交易日志目录运行下面的启动脚本；服务就绪后点「已启动，重试」。
            </p>
            <p className={styles.note}>
              <code className={styles.code}>trade-journal/run.bat</code>
            </p>
          </>
        ) : null}

        {branch === "not_installed" ? (
          <p className={styles.note}>
            没有找到交易日志应用目录。请按交易日志的安装说明完成安装，再重新检测。
          </p>
        ) : null}

        {branch === "probe_failed" ? (
          <>
            <p className={styles.note}>探活请求没有通过，请按顺序检查：</p>
            <ol className={styles.steps}>
              <li>8502 端口是否被其他服务占用。</li>
              <li>本机代理是否拦截了 127.0.0.1，必要时加入直连名单。</li>
              <li>确认后重新检测。</li>
            </ol>
          </>
        ) : null}

        <div className={styles.actions}>
          <Button variant="secondary" onClick={onRetry}>
            {branch === "not_running" ? "已启动，重试" : "重新检测"}
          </Button>
        </div>
      </div>

      {entryUrl === null || entryUrl === "" ? null : (
        <p className={styles.note}>
          入口地址：<code className={styles.code}>{entryUrl}</code>
        </p>
      )}

      <p className={styles.isolation} data-testid="journal-isolation">
        本系统不会读取或修改交易日志的数据。
      </p>
    </>
  );
}
