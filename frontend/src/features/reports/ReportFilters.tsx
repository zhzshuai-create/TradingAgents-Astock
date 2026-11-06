import { useEffect, useId, useState, type KeyboardEvent } from "react";

import type { ReportRating } from "../../api/types";
import { Button } from "../../ui";
import { REPORT_RATING_META } from "./format";
import {
  isReportDate,
  reportListStateHasFilters,
  REPORT_RATING_ORDER,
  type ReportListState,
} from "./listParams";
import styles from "./ReportFilters.module.css";

const CODE_PATTERN = /^\d{6}$/;

export interface ReportFiltersProps {
  state: ReportListState;
  onChange: (patch: Partial<Omit<ReportListState, "cursor">>) => void;
  onReset: () => void;
  compact?: boolean;
  testId?: string;
}

export function ReportFilters({
  state,
  onChange,
  onReset,
  compact = false,
  testId = "report-filters",
}: ReportFiltersProps) {
  const fieldId = useId();
  const [tickerDraft, setTickerDraft] = useState(state.ticker);
  const [tickerError, setTickerError] = useState(false);

  useEffect(() => {
    setTickerDraft(state.ticker);
    setTickerError(false);
  }, [state.ticker]);

  function toggleRating(rating: ReportRating) {
    const checked = state.ratings.includes(rating);
    const next = checked
      ? state.ratings.filter((item) => item !== rating)
      : REPORT_RATING_ORDER.filter(
          (item) => item === rating || state.ratings.includes(item),
        );
    // The contract treats "no rating" as "all"; keep one box ticked instead.
    if (next.length === 0) {
      return;
    }
    onChange({ ratings: next });
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
      (nextFrom === "" || isReportDate(nextFrom)) &&
      (nextTo === "" || isReportDate(nextTo)) &&
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

      <fieldset className={styles.group}>
        <legend className={styles.legend}>评级</legend>
        <div className={styles.ratingGrid}>
          {REPORT_RATING_ORDER.map((rating) => (
            <label
              className={styles.check}
              key={rating}
              data-testid={`filter-rating-${rating}`}
            >
              <input
                type="checkbox"
                checked={state.ratings.includes(rating)}
                onChange={() => toggleRating(rating)}
              />
              <span>{REPORT_RATING_META[rating].label}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className={styles.actions}>
        <Button
          size="sm"
          variant="ghost"
          onClick={reset}
          disabled={!reportListStateHasFilters(state) && state.cursor === null}
        >
          重置
        </Button>
      </div>
    </div>
  );
}
