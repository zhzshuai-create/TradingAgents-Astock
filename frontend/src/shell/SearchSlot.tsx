import { useId, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import styles from "./SearchSlot.module.css";
import { Icon } from "./icons";

export interface SearchSlotProps {
  compact?: boolean;
  autoFocus?: boolean;
}

const CODE_PATTERN = /^\d{6}$/;

export function SearchSlot({ compact = false, autoFocus = false }: SearchSlotProps) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const inputId = useId();
  const errorId = useId();
  const navigate = useNavigate();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = value.trim();
    if (!CODE_PATTERN.test(code)) {
      setError("请输入 6 位股票代码");
      return;
    }
    setError("");
    navigate(`/stocks/${code}`);
  }

  return (
    <form
      className={`${styles.form} ${compact ? styles.compact : ""}`}
      role="search"
      onSubmit={submit}
    >
      <label className={styles.label} htmlFor={inputId}>
        搜索股票
      </label>
      <div className={`${styles.field} ${error ? styles.fieldInvalid : ""}`}>
        <span className={styles.icon} aria-hidden="true">
          <Icon name="search" size={16} />
        </span>
        <input
          id={inputId}
          className={styles.input}
          type="search"
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            setError("");
          }}
          placeholder="输入 6 位股票代码"
          autoComplete="off"
          inputMode="numeric"
          autoFocus={autoFocus}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
        />
        <button type="submit" className={styles.submit} aria-label="提交搜索">
          {compact ? <Icon name="search" size={16} /> : "前往"}
        </button>
      </div>
      {error ? (
        <p className={styles.error} id={errorId} role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
