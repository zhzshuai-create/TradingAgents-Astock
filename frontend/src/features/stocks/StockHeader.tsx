import { Link } from "react-router-dom";

import type { MarketId, StockQuote, StaleReason } from "../../api/types";
import { Badge, Button, DataState } from "../../ui";
import { sourceLabel, type DataStateValue } from "../market/copy";
import {
  changeTone,
  formatMarketTime,
  formatPct,
  formatPrice,
  formatSignedAmount,
  formatSignedPct,
} from "../market/format";
import { formatMoney, formatNumber, toneOf } from "./format";
import { marketLabel } from "./stockParams";
import styles from "./StockPage.module.css";

const TONE_CLASS = {
  up: styles.up,
  down: styles.down,
  flat: styles.flat,
} as const;

export interface StockPrimaryAction {
  label: string;
  onClick: () => void;
}

export interface StockHeaderProps {
  ticker: string;
  market: MarketId | null;
  quote: StockQuote | null;
  state: DataStateValue;
  source: string | null;
  asOf: string | null;
  fetchedAt: string | null;
  partial: boolean;
  failedBlocks: string[];
  staleReason: StaleReason | null;
  onRetry: () => void;
  primary: StockPrimaryAction;
}

interface QuoteField {
  label: string;
  value: string;
  tone?: "up" | "down" | "flat";
}

function quoteFields(quote: StockQuote): QuoteField[] {
  return [
    {
      label: "涨跌额",
      value: formatSignedAmount(quote.change_amt),
      tone: changeTone(quote.change_amt),
    },
    { label: "今开", value: formatPrice(quote.open) },
    { label: "最高", value: formatPrice(quote.high) },
    { label: "最低", value: formatPrice(quote.low) },
    { label: "昨收", value: formatPrice(quote.last_close) },
    { label: "成交额", value: formatMoney(quote.amount_wan, "万元") },
    { label: "换手率", value: formatPct(quote.turnover_pct) },
    { label: "振幅", value: formatPct(quote.amplitude_pct) },
    { label: "PE(TTM)", value: formatNumber(quote.pe_ttm) },
    { label: "PB", value: formatNumber(quote.pb) },
    { label: "流通市值", value: formatMoney(quote.float_mcap_yi, "亿元") },
    { label: "总市值", value: formatMoney(quote.mcap_yi, "亿元") },
    { label: "涨停价", value: formatPrice(quote.limit_up) },
  ];
}

export function StockHeader({
  ticker,
  market,
  quote,
  state,
  source,
  asOf,
  fetchedAt,
  partial,
  failedBlocks,
  staleReason,
  onRetry,
  primary,
}: StockHeaderProps) {
  const name = quote?.name ?? ticker;
  const updated = asOf ?? fetchedAt;

  return (
    <header className={styles.header} data-testid="stock-header">
      <div className={styles.headerTop}>
        <div className={styles.identity}>
          <div className={styles.nameRow}>
            <h1 className={styles.name}>{name}</h1>
            {quote?.name ? <span className={styles.code}>{ticker}</span> : null}
            <Badge tone="neutral">{marketLabel(market)}</Badge>
          </div>
          <p className={styles.meta} data-testid="stock-meta">
            {source === null ? null : <span>来源 {sourceLabel(source)}</span>}
            {updated === null ? null : (
              <span>数据时间 {formatMarketTime(updated)}</span>
            )}
          </p>
        </div>
        <div className={styles.headerActions}>
          <Button
            variant="primary"
            onClick={primary.onClick}
            data-testid="stock-primary-action"
          >
            {primary.label}
          </Button>
          <Link className={styles.headerLink} to={`/reports?ticker=${ticker}`}>
            查看最新报告
          </Link>
          <Link className={styles.headerLink} to={`/jobs?ticker=${ticker}`}>
            查看该股票任务
          </Link>
        </div>
      </div>

      <DataState
        state={state}
        partial={partial}
        failedBlocks={failedBlocks}
        staleReason={staleReason}
        onRetry={onRetry}
        skeletonHeight="150px"
        emptyTitle="暂无行情快照"
        emptyDescription="行情源暂未返回这只股票的快照，稍后再试。"
      >
        {quote === null ? null : (
          <dl className={styles.quoteGrid}>
            <div className={styles.quoteLead}>
              <dt className={styles.quoteLabel}>现价</dt>
              <dd
                className={`${styles.quotePrice} ${
                  TONE_CLASS[toneOf(quote.change_pct)]
                }`}
                data-testid="stock-price"
              >
                {formatPrice(quote.price)}
              </dd>
              <dd
                className={`${styles.quoteChange} ${
                  TONE_CLASS[changeTone(quote.change_pct)]
                }`}
              >
                {formatSignedPct(quote.change_pct)}
              </dd>
            </div>
            {quoteFields(quote).map((field) => (
              <div className={styles.quoteCell} key={field.label}>
                <dt className={styles.quoteLabel}>{field.label}</dt>
                <dd
                  className={
                    field.tone === undefined ? undefined : TONE_CLASS[field.tone]
                  }
                >
                  {field.value}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </DataState>
    </header>
  );
}
