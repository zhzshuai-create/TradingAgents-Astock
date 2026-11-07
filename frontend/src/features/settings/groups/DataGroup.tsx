import { Link } from "react-router-dom";

import type { MetaOptions } from "../../../api/types";
import type { ExportProfile, RefreshProfile } from "../../../lib/preferences";
import styles from "../SettingsView.module.css";

export interface DataGroupProps {
  meta: MetaOptions | undefined;
  refresh: RefreshProfile;
  exportFormat: ExportProfile;
  onRefreshChange: (value: RefreshProfile) => void;
  onExportChange: (value: ExportProfile) => void;
}

export function DataGroup({
  meta,
  refresh,
  exportFormat,
  onRefreshChange,
  onExportChange,
}: DataGroupProps) {
  return (
    <section className={styles.group} aria-labelledby="group-data">
      <h2 id="group-data" className={styles.groupTitle}>
        数据源
      </h2>

      <div className={styles.control}>
        <label className={styles.controlLabel} htmlFor="settings-refresh">
          刷新频率
        </label>
        <select
          id="settings-refresh"
          className={styles.select}
          value={refresh}
          onChange={(event) =>
            onRefreshChange(event.target.value as RefreshProfile)
          }
        >
          <option value="standard">标准</option>
          <option value="relaxed">省流</option>
          <option value="manual">手动</option>
        </select>
      </div>
      <p className={styles.note}>
        偏好只能让刷新等长或变慢；手动档关闭自动刷新，手动刷新按钮仍然可用。
      </p>

      <div className={styles.control}>
        <label className={styles.controlLabel} htmlFor="settings-export">
          导出顺序
        </label>
        <select
          id="settings-export"
          className={styles.select}
          value={exportFormat}
          onChange={(event) =>
            onExportChange(event.target.value as ExportProfile)
          }
        >
          <option value="pdf">PDF 优先</option>
          <option value="markdown">Markdown 优先</option>
        </select>
      </div>
      <p className={styles.note}>
        两种格式始终都能下载，这里只决定报告阅读器里的先后顺序。
      </p>

      <dl className={styles.rows}>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>日志入口地址</dt>
          <dd className={styles.rowValue}>
            {meta?.journal.entry_url ?? "暂不可用"}
          </dd>
        </div>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>数据目录</dt>
          <dd className={styles.rowValue}>由服务端本地管理</dd>
        </div>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>行情数据</dt>
          <dd className={styles.rowValue}>
            以市场页数据为准
            <Link className={styles.inlineLink} to="/market">
              打开市场
            </Link>
          </dd>
        </div>
      </dl>
    </section>
  );
}
