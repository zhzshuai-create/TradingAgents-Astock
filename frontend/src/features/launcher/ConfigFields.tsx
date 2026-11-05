import { useState } from "react";

import type { MetaOptions } from "../../api/types";
import styles from "./ConfigFields.module.css";

export interface ConfigFieldsProps {
  meta: MetaOptions;
  profile: string;
  onProfileChange: (id: string) => void;
  parallel: boolean;
  onParallelChange: (value: boolean) => void;
  toggles: Record<string, boolean>;
  onToggleChange: (id: string, value: boolean) => void;
  profileError?: string;
  configError?: string;
  allowedValues?: string[];
}

export function ConfigFields({
  meta,
  profile,
  onProfileChange,
  parallel,
  onParallelChange,
  toggles,
  onToggleChange,
  profileError,
  configError,
  allowedValues = [],
}: ConfigFieldsProps) {
  const [stagesOpen, setStagesOpen] = useState(false);
  const enabled = meta.stage_toggles.filter(
    (item) => toggles[item.id] ?? item.default,
  ).length;

  return (
    <div className={styles.fields}>
      <div className={styles.row}>
        <label className={styles.label} htmlFor="launcher-profile">
          模型配置
        </label>
        <select
          id="launcher-profile"
          className={styles.select}
          value={profile}
          onChange={(event) => onProfileChange(event.target.value)}
          disabled={meta.llm_profiles.length === 0}
        >
          {meta.llm_profiles.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
        {profileError === undefined ? null : (
          <p className={styles.error} role="alert">
            {profileError}
            {allowedValues.length > 0
              ? `（允许值：${allowedValues.join("、")}）`
              : ""}
          </p>
        )}
      </div>

      <label className={styles.checkRow}>
        <input
          type="checkbox"
          checked={parallel}
          onChange={(event) => onParallelChange(event.target.checked)}
        />
        <span>并行分析</span>
      </label>

      <div className={styles.stages}>
        <button
          type="button"
          className={styles.disclosure}
          aria-expanded={stagesOpen}
          onClick={() => setStagesOpen((value) => !value)}
        >
          <span>
            阶段开关（{enabled}/{meta.stage_toggles.length} 开启）
          </span>
          <span className={styles.disclosureAction} aria-hidden="true">
            {stagesOpen ? "收起" : "展开"}
          </span>
        </button>
        {stagesOpen ? (
          <fieldset className={styles.stageList}>
            <legend className={styles.legend}>关闭后该阶段会在任务里标记为跳过</legend>
            {meta.stage_toggles.map((item) => (
              <label key={item.id} className={styles.checkRow}>
                <input
                  type="checkbox"
                  checked={toggles[item.id] ?? item.default}
                  onChange={(event) =>
                    onToggleChange(item.id, event.target.checked)
                  }
                />
                <span>{item.label}</span>
              </label>
            ))}
          </fieldset>
        ) : null}
        {configError === undefined ? null : (
          <p className={styles.error} role="alert">
            {configError}
            {allowedValues.length > 0
              ? `（允许值：${allowedValues.join("、")}）`
              : ""}
          </p>
        )}
      </div>
    </div>
  );
}
