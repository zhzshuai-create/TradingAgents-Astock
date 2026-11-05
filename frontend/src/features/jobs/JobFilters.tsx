import { useEffect, useId, useState, type KeyboardEvent } from "react";

import type { JobStatus } from "../../api/types";
import { JOB_STATUS_META } from "../../lib/jobStatus";
import { Button } from "../../ui";
import {
  isAnalysisDate,
  JOB_STATUS_ORDER,
  listStateHasFilters,
  type JobListState,
} from "./listParams";
import styles from "./JobFilters.module.css";

const CODE_PATTERN = /^\d{6}$/;

export interface JobFiltersProps {
  state: JobListState;
  onChange: (patch: Partial<Omit<JobListState, "cursor">>) => void;
  onReset: () => void;
  compact?: boolean;
  testId?: string;
}

export function JobFilters({
  state,
  onChange,
  onReset,
  compact = false,
  testId = "job-filters",
}: JobFiltersProps) {
  const fieldId = useId();
  const [tickerDraft, setTickerDraft] = useState(state.ticker);
  const [tickerError, setTickerError] = useState(false);

  useEffect(() => {
    setTickerDraft(state.ticker);
    setTickerError(false);
  }, [state.ticker]);

  function toggleStatus(status: JobStatus) {
    const checked = state.statuses.includes(status);
    const next = checked
      ? state.statuses.filter((item) => item !== status)
      : JOB_STATUS_ORDER.filter(
          (item) => item === status || state.statuses.includes(item),
        );
    // The contract treats "no status" as "all"; keep one box ticked instead.
    if (next.length === 0) {
      return;
    }
    onChange({ statuses: next });
  }

  function commitTicker() {
    const value = tickerDraft.trim();
    if (!CODE_PATTERN.test(value) && value !== "") {
      setTickerError(true);
      return;
    }
    setTickerError(false);
    if (value === state.ticker) {
      return;
    }
    onChange({ ticker: value });
  }

  function reset() {
    setTickerDraft("");
    setTickerError(false);
    onReset();
  }

  function onTickerKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      commitTicker();
    }
    if (event.key === "Escape") {
      setTickerDraft(state.ticker);
      setTickerError(false);
    }
  }

  function changeDate(field: "dateFrom" | "dateTo", value: string) {
    const nextFrom = field === "dateFrom" ? value : state.dateFrom;
    const nextTo = field === "dateTo" ? value : state.dateTo;
    const valid =
      (nextFrom === "" || isAnalysisDate(nextFrom)) &&
      (nextTo === "" || isAnalysisDate(nextTo)) &&
      !(nextFrom !== "" && nextTo !== "" && nextFrom > nextTo);
    if (!valid) {
      onChange({ dateFrom: "", dateTo: "" });
      return;
    }
    onChange({ dateFrom: nextFrom, dateTo: nextTo });
  }

  return (
    <div
      className={`${styles.filters} ${compact ? styles.compact : ""}`}
      data-testid={testId}
    >
      <div className={styles.row}>
        <fieldset className={styles.group} disabled={state.activeOnly}>
          <legend className={styles.legend}>状态</legend>
          <div className={styles.statusGrid}>
            {JOB_STATUS_ORDER.map((status) => (
              <label
                className={styles.check}
                key={status}
                data-testid={`filter-status-${status}`}
              >
                <input
                  type="checkbox"
                  checked={state.statuses.includes(status)}
                  onChange={() => toggleStatus(status)}
                />
                <span>{JOB_STATUS_META[status].label}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className={styles.fields}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={`${fieldId}-ticker`}>
              股票代码
            </label>
            <input
              id={`${fieldId}-ticker`}
              className={styles.input}
              type="text"
              inputMode="numeric"
              maxLength={6}
              placeholder="六位数字"
              value={tickerDraft}
              aria-invalid={tickerError || undefined}
              onChange={(event) => setTickerDraft(event.target.value)}
              onBlur={commitTicker}
              onKeyDown={onTickerKeyDown}
            />
            {tickerError ? (
              <span className={styles.error} role="alert">
                请输入 6 位股票代码
              </span>
            ) : null}
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor={`${fieldId}-from`}>
              开始日期
            </label>
            <input
              id={`${fieldId}-from`}
              className={styles.input}
              type="date"
              value={state.dateFrom}
              max={state.dateTo || undefined}
              onChange={(event) => changeDate("dateFrom", event.target.value)}
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor={`${fieldId}-to`}>
              结束日期
            </label>
            <input
              id={`${fieldId}-to`}
              className={styles.input}
              type="date"
              value={state.dateTo}
              min={state.dateFrom || undefined}
              onChange={(event) => changeDate("dateTo", event.target.value)}
            />
          </div>
        </div>
      </div>

      <div className={styles.actions}>
        <label className={styles.switch} data-testid="filter-active">
          <input
            type="checkbox"
            checked={state.activeOnly}
            onChange={(event) => onChange({ activeOnly: event.target.checked })}
          />
          <span>只看活动任务</span>
        </label>
        {state.activeOnly ? (
          <span className={styles.hint}>活动任务不按状态筛选</span>
        ) : null}
        <Button
          size="sm"
          variant="ghost"
          onClick={reset}
          disabled={!listStateHasFilters(state) && state.cursor === null}
        >
          重置
        </Button>
      </div>
    </div>
  );
}
