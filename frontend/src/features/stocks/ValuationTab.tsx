import { useQuery } from "@tanstack/react-query";

import type {
  FundFlowData,
  SectorBlockItem,
  StockSnapshotData,
} from "../../api/types";
import { stockFundFlowQuery } from "../../lib/query";
import { DataState } from "../../ui";
import type { DataStateValue } from "../market/copy";
import { envelopeState } from "../market/state";
import { formatPct } from "../market/format";
import { formatNumber } from "./format";
import styles from "./StockPage.module.css";

export interface ValuationTabProps {
  ticker: string;
  snapshot: StockSnapshotData | null;
  snapshotState: DataStateValue;
  onRetrySnapshot: () => void;
}

interface Field {
  label: string;
  value: string;
  missing?: boolean;
}

function valuationFields(snapshot: StockSnapshotData): Field[] {
  const { quote, valuation } = snapshot;
  const fields: Field[] = [];
  if (quote !== null) {
    fields.push(
      { label: "现价", value: formatNumber(quote.price) },
      { label: "涨跌幅", value: formatPct(quote.change_pct) },
      { label: "PE(TTM)", value: formatNumber(quote.pe_ttm) },
      { label: "PB", value: formatNumber(quote.pb) },
      { label: "总市值（亿元）", value: formatNumber(quote.mcap_yi) },
      { label: "流通市值（亿元）", value: formatNumber(quote.float_mcap_yi) },
      { label: "换手率", value: formatPct(quote.turnover_pct) },
      { label: "成交额（万元）", value: formatNumber(quote.amount_wan) },
    );
  }
  const eps = valuation?.eps_forecast ?? null;
  const forward = valuation?.pe_forward ?? null;
  const peg = valuation?.peg ?? null;
  const years = valuation?.pe_digestion_years ?? null;
  fields.push(
    { label: "一致预期 EPS", value: formatNumber(eps), missing: eps === null },
    {
      label: "动态 PE",
      value: formatNumber(forward),
      missing: forward === null,
    },
    { label: "PEG", value: formatNumber(peg), missing: peg === null },
    {
      label: "消化估值年数",
      value: formatNumber(years),
      missing: years === null,
    },
  );
  return fields;
}

const SECTOR_GROUPS: Array<{
  key: "industry" | "concept" | "region";
  label: string;
}> = [
  { key: "industry", label: "行业" },
  { key: "concept", label: "概念" },
  { key: "region", label: "地域" },
];

function SectorGroup({
  label,
  items,
}: {
  label: string;
  items: SectorBlockItem[];
}) {
  return (
    <div className={styles.sectorGroup} data-testid="sector-group">
      <h3 className={styles.blockTitle}>{label}</h3>
      {items.length === 0 ? (
        <p className={styles.blockNote}>暂无{label}板块数据</p>
      ) : (
        <ul className={styles.sectorList}>
          {items.map((item) => (
            <li className={styles.sectorItem} key={`${label}-${item.name}`}>
              <span className={styles.sectorName}>{item.name}</span>
              <span className={styles.sectorChange}>
                {formatPct(item.change_pct)}
              </span>
              {item.desc === "" ? null : (
                <span className={styles.sectorDesc}>{item.desc}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const FLOW_COLUMNS: Array<{ key: keyof FundFlowData["items"][number]; label: string }> =
  [
    { key: "main_net", label: "主力净额" },
    { key: "super_net", label: "超大单" },
    { key: "large_net", label: "大单" },
    { key: "mid_net", label: "中单" },
    { key: "small_net", label: "小单" },
  ];

function FundFlowBlock({ ticker }: { ticker: string }) {
  const query = useQuery(stockFundFlowQuery(ticker));
  const state = envelopeState(query);
  const items = query.data?.data?.items ?? [];

  return (
    <section className={styles.block} aria-labelledby="stock-fund-flow-title">
      <h3 className={styles.blockTitle} id="stock-fund-flow-title">
        资金流（元）
      </h3>
      <DataState
        state={state === "ok" && items.length === 0 ? "empty" : state}
        partial={query.data?.partial ?? false}
        failedBlocks={query.data?.failed_blocks ?? []}
        staleReason={query.data?.stale_reason ?? null}
        onRetry={() => void query.refetch()}
        skeletonHeight="180px"
        emptyTitle="暂无资金流数据"
        emptyDescription="资金流数据暂未返回。"
      >
        <div className={styles.tableScroll}>
          <table className={styles.table} data-testid="fund-flow-table">
            <thead>
              <tr>
                <th scope="col">时间</th>
                {FLOW_COLUMNS.map((column) => (
                  <th scope="col" key={column.key}>
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.time} data-testid="fund-flow-row">
                  <td>{item.time}</td>
                  {FLOW_COLUMNS.map((column) => (
                    <td key={column.key} className={styles.numeric}>
                      {formatNumber(item[column.key] as number)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DataState>
    </section>
  );
}

export function ValuationTab({
  ticker,
  snapshot,
  snapshotState,
  onRetrySnapshot,
}: ValuationTabProps) {
  if (snapshotState === "loading" || snapshotState === "error") {
    return (
      <DataState
        state={snapshotState}
        onRetry={onRetrySnapshot}
        skeletonHeight="360px"
      />
    );
  }
  if (snapshot === null) {
    return (
      <DataState
        state="empty"
        emptyTitle="暂无估值数据"
        emptyDescription="快照数据暂未返回。"
      />
    );
  }

  const fields = valuationFields(snapshot);
  const valuationMissing = snapshot.valuation === null;
  const sectors = snapshot.sector_blocks;

  return (
    <div className={styles.tabPanel} data-testid="stock-valuation">
      <section className={styles.block} aria-labelledby="stock-figures-title">
        <h3 className={styles.blockTitle} id="stock-figures-title">
          行情与估值
        </h3>
        <dl className={styles.fieldGrid}>
          {fields.map((field) => (
            <div className={styles.field} key={field.label}>
              <dt className={styles.fieldLabel}>{field.label}</dt>
              <dd
                className={field.missing === true ? styles.missing : styles.fieldValue}
                data-testid="valuation-field"
                data-missing={field.missing === true ? "true" : "false"}
              >
                {field.value}
              </dd>
            </div>
          ))}
        </dl>
        <p className={styles.blockNote} data-testid="valuation-note">
          {valuationMissing
            ? "一致预期与估值推算不可得：数据源未返回可用值，缺失字段显示「—」。"
            : "缺失字段显示「—」，表示按当前数据无法计算，不用 0 代替。"}
        </p>
      </section>

      <section className={styles.block} aria-labelledby="stock-sectors-title">
        <h3 className={styles.blockTitle} id="stock-sectors-title">
          板块归属
        </h3>
        {sectors === null ? (
          <p className={styles.blockNote} data-testid="sector-note">
            板块数据不可得：数据源未返回行业、概念与地域。
          </p>
        ) : (
          <div className={styles.sectorGrid}>
            {SECTOR_GROUPS.map((group) => (
              <SectorGroup
                key={group.key}
                label={group.label}
                items={sectors[group.key]}
              />
            ))}
          </div>
        )}
      </section>

      <FundFlowBlock ticker={ticker} />
    </div>
  );
}
