import type { CreateJobRequest, MetaOptions } from "../../api/types";

export interface TickerSelection {
  code: string;
  /** Null when the code came from a deep link or a typed code. */
  name: string | null;
}

export interface LauncherValues {
  ticker: TickerSelection | null;
  analysisDate: string;
  llmProfile: string;
  parallelAnalysts: boolean;
  stageToggles: Record<string, boolean>;
}

/** Only the toggles the server advertises, with the server's defaults. */
export function defaultStageToggles(
  meta: MetaOptions | undefined,
): Record<string, boolean> {
  const toggles: Record<string, boolean> = {};
  for (const item of meta?.stage_toggles ?? []) {
    toggles[item.id] = item.default;
  }
  return toggles;
}

export function toCreateJobRequest(values: LauncherValues): CreateJobRequest {
  return {
    ticker: values.ticker?.code ?? "",
    analysis_date: values.analysisDate,
    config: {
      llm_profile: values.llmProfile,
      parallel_analysts: values.parallelAnalysts,
      stage_toggles: values.stageToggles,
    },
  };
}
