import type { MetaOptions } from "../../../api/types";
import styles from "../SettingsView.module.css";

export interface ModelGroupProps {
  meta: MetaOptions | undefined;
  llmProfile: string | undefined;
  parallelAnalysts: boolean;
  onProfileChange: (id: string) => void;
  onParallelChange: (checked: boolean) => void;
}

export function ModelGroup({
  meta,
  llmProfile,
  parallelAnalysts,
  onProfileChange,
  onParallelChange,
}: ModelGroupProps) {
  const profiles = meta?.llm_profiles ?? [];
  const known =
    llmProfile !== undefined && profiles.some((item) => item.id === llmProfile);
  // A stored id that disappeared from the server list falls back for display
  // only; the stored value is left alone until the user chooses.
  const selected = known ? llmProfile : "";

  return (
    <section className={styles.group} aria-labelledby="group-model">
      <h2 id="group-model" className={styles.groupTitle}>
        模型
      </h2>

      <div className={styles.control}>
        <label className={styles.controlLabel} htmlFor="settings-default-model">
          默认模型
        </label>
        <select
          id="settings-default-model"
          className={styles.select}
          value={selected}
          disabled={profiles.length === 0}
          onChange={(event) => onProfileChange(event.target.value)}
        >
          <option value="">跟随服务端默认</option>
          {profiles.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
      </div>
      <p className={styles.note}>
        这里只保存本机默认值，启动器用它预填新任务；已有任务的配置快照不受影响。
      </p>

      <div className={styles.control}>
        <label className={styles.checkRow}>
          <input
            type="checkbox"
            checked={parallelAnalysts}
            onChange={(event) => onParallelChange(event.target.checked)}
          />
          <span>默认并行分析师</span>
        </label>
      </div>
      <p className={styles.note}>并行分析师仍属实验性能力，耗时与结果可能与串行不同。</p>

      <div className={styles.subgroup}>
        <h3 className={styles.subTitle}>服务端模型配置</h3>
        {profiles.length === 0 ? (
          <p className={styles.note}>
            {meta === undefined ? "正在读取模型列表…" : "服务端没有提供模型配置。"}
          </p>
        ) : (
          <ul className={styles.profileList}>
            {profiles.map((item) => (
              <li key={item.id} className={styles.profileItem}>
                <span className={styles.profileName}>{item.label}</span>
                <code className={styles.profileId}>{item.id}</code>
              </li>
            ))}
          </ul>
        )}
        <p className={styles.note}>
          模型密钥与 Base URL 由服务端环境变量配置，本页不提供输入。
        </p>
      </div>
    </section>
  );
}
