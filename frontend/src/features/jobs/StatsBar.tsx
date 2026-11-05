import type { JobStats } from "../../api/types";
import { formatDuration } from "./format";
import styles from "./StatsBar.module.css";

interface StatsBarProps {
  stats: JobStats;
}

function count(value: number): string {
  return value.toLocaleString("zh-CN");
}

export function StatsBar({ stats }: StatsBarProps) {
  return (
    <section className={styles.bar} aria-label="任务统计" data-testid="job-stats">
      <div className={styles.cell}>
        <span className={styles.label}>模型调用</span>
        <span className={styles.value} data-testid="stat-model-calls">
          {count(stats.model_calls)}
        </span>
      </div>
      <div className={styles.cell}>
        <span className={styles.label}>输入 Tokens</span>
        <span className={styles.value} data-testid="stat-tokens-in">
          {count(stats.tokens_in)}
        </span>
      </div>
      <div className={styles.cell}>
        <span className={styles.label}>输出 Tokens</span>
        <span className={styles.value} data-testid="stat-tokens-out">
          {count(stats.tokens_out)}
        </span>
      </div>
      <div className={styles.cell}>
        <span className={styles.label}>耗时</span>
        <span className={styles.value} data-testid="stat-elapsed">
          {formatDuration(stats.elapsed_ms)}
        </span>
      </div>
    </section>
  );
}
