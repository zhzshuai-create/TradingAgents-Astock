import {
  useId,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";

import type { MarketSearchItem, MarketId } from "../../api/types";
import { Icon } from "../../shell/icons";
import styles from "./SearchBox.module.css";
import { useStockSearch } from "./useStockSearch";

const CODE_PATTERN = /^\d{6}$/;

const MARKET_LABELS: Record<MarketId, string> = {
  sh: "沪市",
  sz: "深市",
  bj: "北交所",
};

export interface SearchBoxProps {
  compact?: boolean;
  autoFocus?: boolean;
}

export function SearchBox({ compact = false, autoFocus = false }: SearchBoxProps) {
  const [value, setValue] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const inputId = useId();
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { query, items, isLoading, error, truncated, retry } = useStockSearch(value);

  const trimmed = value.trim();
  const pendingInput = trimmed !== query;
  const waiting = pendingInput || isLoading;
  const visibleItems = waiting ? [] : items;
  const showPanel = open && trimmed.length >= 1;
  const showEmpty = !waiting && error === null && query.length > 0 && items.length === 0;
  const showError = !pendingInput && error !== null;

  function targetFor(code: string): string {
    return pathname === "/workbench"
      ? `/workbench?launch=1&ticker=${code}`
      : `/stocks/${code}`;
  }

  function finish(path: string) {
    navigate(path);
    setValue("");
    setActive(-1);
    setOpen(false);
    inputRef.current?.blur();
  }

  function choose(item: MarketSearchItem) {
    finish(targetFor(item.ticker_code));
  }

  function submitCode(): boolean {
    const code = trimmed;
    if (!CODE_PATTERN.test(code)) {
      return false;
    }
    finish(targetFor(code));
    return true;
  }

  function execute() {
    const highlighted = active >= 0 ? visibleItems[active] : undefined;
    if (highlighted) {
      choose(highlighted);
      return;
    }
    if (visibleItems.length > 0) {
      choose(visibleItems[0]);
      return;
    }
    submitCode();
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      if (visibleItems.length > 0) {
        setActive((index) => (index + 1 >= visibleItems.length ? 0 : index + 1));
      }
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (visibleItems.length > 0) {
        setActive((index) =>
          index <= 0 ? visibleItems.length - 1 : index - 1,
        );
      }
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      execute();
      return;
    }
    if (event.key === "Escape") {
      setOpen(false);
      setActive(-1);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    execute();
  }

  return (
    <form
      role="search"
      className={`${styles.form} ${compact ? styles.compact : ""}`}
      onSubmit={onSubmit}
    >
      <label className={styles.label} htmlFor={inputId}>
        搜索股票
      </label>
      <div className={`${styles.field} ${showError ? styles.fieldInvalid : ""}`}>
        <span className={styles.icon} aria-hidden="true">
          <Icon name="search" size={16} />
        </span>
        <input
          ref={inputRef}
          id={inputId}
          className={styles.input}
          type="search"
          role="combobox"
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            setActive(-1);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            window.setTimeout(() => setOpen(false), 120);
          }}
          onKeyDown={onKeyDown}
          placeholder="输入股票代码或名称"
          autoComplete="off"
          autoFocus={autoFocus}
          aria-autocomplete="list"
          aria-expanded={showPanel}
          aria-controls={showPanel ? listId : undefined}
          aria-activedescendant={
            showPanel && active >= 0 ? `${listId}-${active}` : undefined
          }
          aria-invalid={showError ? true : undefined}
        />
        <button type="submit" className={styles.submit} aria-label="提交搜索">
          {compact ? <Icon name="search" size={16} /> : "搜索"}
        </button>
      </div>
      {showPanel ? (
        <div
          className={styles.panel}
          id={listId}
          role="listbox"
          aria-label="搜索结果"
          onMouseDown={(event) => event.preventDefault()}
        >
          {waiting ? <p className={styles.hint}>搜索中…</p> : null}
          {showError ? (
            <div className={styles.errorRow} role="alert">
              <span className={styles.errorText}>{error}</span>
              <button type="button" className={styles.retry} onClick={retry}>
                重试
              </button>
            </div>
          ) : null}
          {showEmpty ? (
            <p className={styles.hint}>没有找到，检查代码或名称</p>
          ) : null}
          {visibleItems.map((item, index) => (
            <div
              key={`${item.ticker_code}-${index}`}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              className={`${styles.option} ${index === active ? styles.active : ""}`}
              onMouseDown={() => choose(item)}
            >
              <span className={styles.optionName}>{item.ticker_name}</span>
              <span className={styles.optionMeta}>
                {item.ticker_code} · {MARKET_LABELS[item.market]}
              </span>
            </div>
          ))}
          {!waiting && truncated ? (
            <p className={styles.hint}>只显示前 10 条，再输入几个字缩小范围</p>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}
