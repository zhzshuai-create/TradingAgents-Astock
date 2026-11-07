import { useQuery } from "@tanstack/react-query";
import { useCallback, useState, useSyncExternalStore } from "react";

import {
  readLastSseResult,
  subscribeLastSseResult,
  type SseLastResult,
} from "../../api/sse";
import { metaOptionsQuery } from "../../lib/query";
import {
  setPreferences,
  usePreferences,
  type Preferences,
} from "../../lib/preferences";
import { useIsMobile } from "../market/useIsMobile";
import { AboutGroup } from "./groups/AboutGroup";
import { BasicGroup } from "./groups/BasicGroup";
import { DataGroup } from "./groups/DataGroup";
import { ModelGroup } from "./groups/ModelGroup";
import styles from "./SettingsView.module.css";
import {
  SETTINGS_GROUPS,
  SETTINGS_GROUP_LABELS,
  useSettingsGroup,
  type SettingsGroup,
} from "./useSettingsGroup";

const GROUP_HINTS: Record<SettingsGroup, string> = {
  basic: "版本、接口与日志状态",
  model: "默认模型与并行分析师",
  data: "刷新、导出与数据入口",
  about: "版本、许可与免责声明",
};

const NONE_FALLBACK = (): SseLastResult => "none";

export function SettingsView() {
  const isMobile = useIsMobile();
  const metaQuery = useQuery(metaOptionsQuery);
  const preferences = usePreferences();
  const lastSseResult = useSyncExternalStore(
    subscribeLastSseResult,
    readLastSseResult,
    NONE_FALLBACK,
  );
  const { group, select, close } = useSettingsGroup();
  const [saved, setSaved] = useState(false);

  const save = useCallback((patch: Partial<Preferences>) => {
    setPreferences(patch);
    setSaved(true);
  }, []);

  const metaFailed = metaQuery.isError && metaQuery.data === undefined;

  const renderGroup = (target: SettingsGroup) => {
    switch (target) {
      case "basic":
        return (
          <BasicGroup
            key={target}
            meta={metaQuery.data}
            failed={metaFailed}
            lastSseResult={lastSseResult}
            density={preferences.density}
            onDensityChange={(density) => save({ density })}
            onRetry={() => {
              void metaQuery.refetch();
            }}
          />
        );
      case "model":
        return (
          <ModelGroup
            key={target}
            meta={metaQuery.data}
            llmProfile={preferences.launcher.llm_profile}
            parallelAnalysts={preferences.launcher.parallel_analysts ?? false}
            onProfileChange={(llm_profile) => save({ launcher: { llm_profile } })}
            onParallelChange={(parallel_analysts) =>
              save({ launcher: { parallel_analysts } })
            }
          />
        );
      case "data":
        return (
          <DataGroup
            key={target}
            meta={metaQuery.data}
            refresh={preferences.refresh}
            exportFormat={preferences.export}
            onRefreshChange={(refresh) => save({ refresh })}
            onExportChange={(exportFormat) => save({ export: exportFormat })}
          />
        );
      case "about":
        return <AboutGroup key={target} meta={metaQuery.data} />;
    }
  };

  return (
    <section className={styles.page} data-testid="page-settings">
      <header className={styles.pageHead}>
        <h1 className={styles.title}>设置</h1>
        <p className={styles.lead}>
          本页只展示冻结契约给得起的信息；偏好只保存在本机，修改只影响新任务的默认值。
        </p>
      </header>

      <p className={styles.saved} role="status" aria-live="polite">
        {saved ? "已保存" : ""}
      </p>

      {isMobile ? (
        group === null ? (
          <nav className={styles.groupList} aria-label="设置分组">
            {SETTINGS_GROUPS.map((item) => (
              <button
                key={item}
                type="button"
                className={styles.groupRow}
                data-group={item}
                onClick={() => select(item)}
              >
                <span className={styles.groupRowText}>
                  <span className={styles.groupRowName}>
                    {SETTINGS_GROUP_LABELS[item]}
                  </span>
                  <span className={styles.groupRowHint}>{GROUP_HINTS[item]}</span>
                </span>
                <span className={styles.groupRowChevron} aria-hidden="true">
                  ›
                </span>
              </button>
            ))}
          </nav>
        ) : (
          <div className={styles.detail}>
            <button type="button" className={styles.back} onClick={close}>
              返回设置
            </button>
            {renderGroup(group)}
          </div>
        )
      ) : (
        <div className={styles.groups}>{SETTINGS_GROUPS.map(renderGroup)}</div>
      )}
    </section>
  );
}
