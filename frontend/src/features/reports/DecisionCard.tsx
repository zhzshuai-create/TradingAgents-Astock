import type { ReportMeta } from "../../api/types";
import { Badge } from "../../ui";
import { REPORT_RATING_META } from "./format";
import styles from "./DecisionCard.module.css";

/** Missing decision fields are shown as an em dash, never guessed. */
export const EMPTY_VALUE = "—";

function display(value: string | number | null | undefined): string {
  if (value === null || value === undefined) {
    return EMPTY_VALUE;
  }
  const text = String(value).trim();
  return text === "" ? EMPTY_VALUE : text;
}

/** ``unknown`` is the DTO sentinel for "not recorded", not a real signal. */
function signalText(signal: ReportMeta["signal"]): string {
  return signal === "unknown" ? EMPTY_VALUE : display(signal);
}

export function DecisionCard({ meta }: { meta: ReportMeta }) {
  const rating = REPORT_RATING_META[meta.rating];
  return (
    <section className={styles.card} aria-label="决策卡" data-testid="decision-card">
      <h2 className={styles.heading}>决策</h2>
      <dl className={styles.rows}>
        <div className={styles.row}>
          <dt>评级</dt>
          <dd data-testid="decision-rating">
            <Badge tone={rating.tone}>{rating.label}</Badge>
          </dd>
        </div>
        <div className={styles.row}>
          <dt>信号</dt>
          <dd data-testid="decision-signal">{signalText(meta.signal)}</dd>
        </div>
        <div className={styles.row}>
          <dt>目标价</dt>
          <dd data-testid="decision-price-target">
            {display(meta.price_target)}
          </dd>
        </div>
        <div className={styles.row}>
          <dt>止损参考</dt>
          <dd data-testid="decision-stop">{display(meta.stop_reference)}</dd>
        </div>
        <div className={styles.row}>
          <dt>时间跨度</dt>
          <dd data-testid="decision-horizon">{display(meta.time_horizon)}</dd>
        </div>
      </dl>
    </section>
  );
}
