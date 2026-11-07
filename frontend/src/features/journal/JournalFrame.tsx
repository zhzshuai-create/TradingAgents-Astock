/** Available state: one status row and one scroll container, no page scroll. */

import { useState } from "react";

import { Button } from "../../ui";
import styles from "./JournalPage.module.css";
import { useJournalThemeBridge } from "./useJournalThemeBridge";

export interface JournalFrameProps {
  entryUrl: string;
}

export function JournalFrame({ entryUrl }: JournalFrameProps) {
  const { frameRef, sendTheme } = useJournalThemeBridge(entryUrl);
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <div className={styles.frameShell}>
      <header className={styles.frameHead} data-testid="journal-frame-head">
        <div className={styles.frameHeadText}>
          <h1 className={styles.title}>交易日志</h1>
          <span className={styles.running} role="status">
            日志服务运行中
          </span>
        </div>
        <div className={styles.frameActions}>
          <a
            className={styles.linkButton}
            href={entryUrl}
            target="_blank"
            rel="noreferrer"
            data-testid="journal-new-window"
          >
            新窗口打开
          </a>
          <Button
            variant="secondary"
            data-testid="journal-refresh"
            onClick={() => setReloadKey((value) => value + 1)}
          >
            刷新
          </Button>
        </div>
      </header>
      <div className={styles.frameBox}>
        <iframe
          key={reloadKey}
          ref={frameRef}
          className={styles.frame}
          src={entryUrl}
          title="交易日志"
          onLoad={sendTheme}
        />
      </div>
    </div>
  );
}
