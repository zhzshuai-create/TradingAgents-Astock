import { useState } from "react";

import { Button } from "../../ui";
import { SearchBox } from "../search/SearchBox";
import type { TickerCandidate } from "./submitErrors";
import styles from "./TickerField.module.css";
import type { TickerSelection } from "./types";

export interface TickerFieldProps {
  value: TickerSelection | null;
  onChange: (value: TickerSelection) => void;
  error?: string;
  candidates?: TickerCandidate[];
}

export function TickerField({
  value,
  onChange,
  error,
  candidates = [],
}: TickerFieldProps) {
  const [changing, setChanging] = useState(false);
  const editing = value === null || changing;

  function pick(selection: TickerSelection) {
    onChange(selection);
    setChanging(false);
  }

  return (
    <div className={styles.field}>
      <p className={styles.label} id="launcher-ticker-label">
        股票
      </p>
      {value !== null && !editing ? (
        <div className={styles.selected}>
          <span className={styles.identity} aria-labelledby="launcher-ticker-label">
            {value.name === null ? null : (
              <span className={styles.name}>{value.name}</span>
            )}
            <span className={styles.code}>{value.code}</span>
          </span>
          <div className={styles.actions}>
            <Button size="sm" variant="ghost" onClick={() => setChanging(true)}>
              更换
            </Button>
          </div>
        </div>
      ) : (
        <div className={styles.search}>
          <SearchBox
            label="搜索股票代码或名称"
            onSelect={({ code, name }) => pick({ code, name })}
          />
          {value === null ? null : (
            <Button size="sm" variant="ghost" onClick={() => setChanging(false)}>
              取消更换
            </Button>
          )}
        </div>
      )}
      {error === undefined ? null : (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {candidates.length === 0 ? null : (
        <div className={styles.candidates}>
          <p className={styles.hint}>请选择一只：</p>
          <ul className={styles.list}>
            {candidates.map((candidate) => (
              <li key={candidate.code}>
                <button
                  type="button"
                  className={styles.candidate}
                  onClick={() =>
                    pick({ code: candidate.code, name: candidate.name })
                  }
                >
                  <span>{candidate.name}</span>
                  <span className={styles.candidateCode}>{candidate.code}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
