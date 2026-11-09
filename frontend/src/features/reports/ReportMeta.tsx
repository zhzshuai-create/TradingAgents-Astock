import { Link } from "react-router-dom";

import type { ReportMeta as ReportMetaDto } from "../../api/types";
import {
  CHART_SNAPSHOT_LABELS,
  DATA_QUALITY_LABELS,
  formatGeneratedAt,
  originLabel,
} from "./format";
import styles from "./ReportMeta.module.css";

/** Right-column provenance: time, origin, data quality and the source job. */
export function ReportMeta({ meta }: { meta: ReportMetaDto }) {
  return (
    <section
      className={styles.card}
      aria-label="报告元信息"
      data-testid="report-meta"
    >
      <h2 className={styles.heading}>元信息</h2>
      <dl className={styles.rows}>
        <div className={styles.row}>
          <dt>生成时间</dt>
          <dd data-testid="meta-generated-at">
            {formatGeneratedAt(meta.generated_at)}
          </dd>
        </div>
        <div className={styles.row}>
          <dt>来源</dt>
          <dd data-testid="meta-origin">{originLabel({ meta })}</dd>
        </div>
        <div className={styles.row}>
          <dt>数据质量</dt>
          <dd data-testid="meta-data-quality">
            {DATA_QUALITY_LABELS[meta.data_quality_status]}
          </dd>
        </div>
        <div className={styles.row}>
          <dt>图表快照</dt>
          <dd data-testid="meta-chart-snapshot">
            {CHART_SNAPSHOT_LABELS[meta.chart_snapshot_status]}
          </dd>
        </div>
        {meta.job_id === null ? null : (
          <div className={styles.row}>
            <dt>来源任务</dt>
            <dd>
              <Link
                className={styles.link}
                to={`/jobs/${meta.job_id}`}
                data-testid="meta-job"
              >
                查看任务
              </Link>
            </dd>
          </div>
        )}
      </dl>
    </section>
  );
}
