import { Link } from "react-router-dom";

import type { JournalReason, MetaOptions } from "../../../api/types";
import type { SseLastResult } from "../../../api/sse";
import type { Density } from "../../../lib/preferences";
import styles from "../SettingsView.module.css";

const SSE_RESULT_TEXT: Record<SseLastResult, string> = {
  none: "未连接",
  success: "最近一次连接成功",
  failure: "最近一次连接失败",
};

const JOURNAL_REASON_TEXT: Record<JournalReason, string> = {
  not_running: "日志服务当前没有在运行",
  not_installed: "日志服务尚未安装",
  probe_failed: "日志端口探测失败",
};

export interface BasicGroupProps {
  meta: MetaOptions | undefined;
  failed: boolean;
  lastSseResult: SseLastResult;
  density: Density;
  onDensityChange: (density: Density) => void;
  onRetry: () => void;
}

function journalText(meta: MetaOptions | undefined): string {
  if (meta === undefined) {
    return "暂不可用";
  }
  if (meta.journal.available) {
    return "日志服务运行中";
  }
  return meta.journal.reason === null
    ? "日志服务未就绪"
    : JOURNAL_REASON_TEXT[meta.journal.reason];
}

export function BasicGroup({
  meta,
  failed,
  lastSseResult,
  density,
  onDensityChange,
  onRetry,
}: BasicGroupProps) {
  let apiState = "正在读取…";
  if (failed) {
    apiState = "接口不可达";
  } else if (meta !== undefined) {
    apiState = "接口可达";
  }

  return (
    <section className={styles.group} aria-labelledby="group-basic">
      <h2 id="group-basic" className={styles.groupTitle}>
        基本
      </h2>
      <dl className={styles.rows}>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>接口状态</dt>
          <dd className={styles.rowValue}>
            {apiState}
            {failed ? (
              <button type="button" className={styles.inlineButton} onClick={onRetry}>
                重试
              </button>
            ) : null}
          </dd>
        </div>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>SSE 最近结果</dt>
          <dd className={styles.rowValue}>{SSE_RESULT_TEXT[lastSseResult]}</dd>
        </div>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>应用版本</dt>
          <dd className={styles.rowValue}>{meta?.app_version ?? "暂不可用"}</dd>
        </div>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>契约版本</dt>
          <dd className={styles.rowValue}>{meta?.contract_version ?? "暂不可用"}</dd>
        </div>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>服务器时间</dt>
          <dd className={styles.rowValue}>{meta?.server_time ?? "暂不可用"}</dd>
        </div>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>交易日志</dt>
          <dd className={styles.rowValue}>
            {journalText(meta)}
            <Link className={styles.inlineLink} to="/journal">
              打开交易日志
            </Link>
          </dd>
        </div>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>后台任务</dt>
          <dd className={styles.rowValue}>
            以任务页活动任务为准
            <Link className={styles.inlineLink} to="/jobs">
              查看活动任务
            </Link>
          </dd>
        </div>
      </dl>

      <div className={styles.control}>
        <label className={styles.controlLabel} htmlFor="settings-density">
          列表密度
        </label>
        <select
          id="settings-density"
          className={styles.select}
          value={density}
          onChange={(event) => onDensityChange(event.target.value as Density)}
        >
          <option value="comfortable">标准</option>
          <option value="compact">紧凑</option>
        </select>
      </div>
      <p className={styles.note}>紧凑密度只影响桌面列表，移动端保持标准行高。</p>
    </section>
  );
}
