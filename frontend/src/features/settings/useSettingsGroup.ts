/** P5-03 5.1: ``#group-*`` deep links without a second route. */

import { useCallback, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";

export const SETTINGS_GROUPS = ["basic", "model", "data", "about"] as const;

export type SettingsGroup = (typeof SETTINGS_GROUPS)[number];

export const SETTINGS_GROUP_LABELS: Record<SettingsGroup, string> = {
  basic: "基本",
  model: "模型",
  data: "数据源",
  about: "关于",
};

export function settingsGroupId(group: SettingsGroup): string {
  return `group-${group}`;
}

const GROUP_HASH = /^#group-(basic|model|data|about)$/;

/** An unknown hash is not a fallback group: callers stay where they are. */
export function parseSettingsGroup(hash: string): SettingsGroup | null {
  const match = GROUP_HASH.exec(hash);
  return match === null ? null : (match[1] as SettingsGroup);
}

export function useSettingsGroup() {
  const location = useLocation();
  const navigate = useNavigate();
  const group = parseSettingsGroup(location.hash);

  const select = useCallback(
    (next: SettingsGroup) => {
      navigate({ hash: settingsGroupId(next) });
    },
    [navigate],
  );

  const close = useCallback(() => {
    navigate({ hash: "" });
  }, [navigate]);

  useEffect(() => {
    if (group === null) {
      return;
    }
    const target = document.getElementById(settingsGroupId(group));
    target?.scrollIntoView?.({ block: "start" });
  }, [group]);

  return { group, select, close };
}
