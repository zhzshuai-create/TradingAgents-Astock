import type { MetaOptions } from "../../../api/types";
import { Icon } from "../../../shell/icons";
import { LEGACY_ENTRY_URL } from "../../../shell/navigation";
import styles from "../SettingsView.module.css";

export interface AboutGroupProps {
  meta: MetaOptions | undefined;
}

export function AboutGroup({ meta }: AboutGroupProps) {
  return (
    <section className={styles.group} aria-labelledby="group-about">
      <h2 id="group-about" className={styles.groupTitle}>
        关于
      </h2>
      <dl className={styles.rows}>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>版本</dt>
          <dd className={styles.rowValue}>{meta?.app_version ?? "暂不可用"}</dd>
        </div>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>构建说明</dt>
          <dd className={styles.rowValue}>
            React 19 + Vite 前端，读取服务端契约{" "}
            {meta?.contract_version ?? "暂不可用"}
          </dd>
        </div>
        <div className={styles.row}>
          <dt className={styles.rowLabel}>旧版入口</dt>
          <dd className={styles.rowValue}>
            <a
              className={styles.inlineLink}
              href={LEGACY_ENTRY_URL}
              target="_blank"
              rel="noreferrer"
              data-testid="about-legacy-entry"
            >
              <Icon name="external" size={14} />
              打开旧版界面
            </a>
          </dd>
        </div>
      </dl>

      <div className={styles.subgroup}>
        <h3 className={styles.subTitle}>许可与免责声明</h3>
        <p className={styles.note}>
          本系统是研究与分析辅助工具，输出不构成任何投资建议。行情与财务数据以交易所、数据源
          及服务端返回为准；据此操作的风险由使用者自行承担。
        </p>
        <p className={styles.note}>
          第三方数据遵循各自授权，具体许可以各数据源发布的信息为准。
        </p>
      </div>
    </section>
  );
}
