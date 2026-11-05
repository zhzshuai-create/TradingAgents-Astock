import type { CSSProperties } from "react";

import styles from "./Skeleton.module.css";

export interface SkeletonProps {
  width?: CSSProperties["width"];
  height?: CSSProperties["height"];
  radius?: string;
  className?: string;
}

export function Skeleton({
  width = "100%",
  height = "1em",
  radius,
  className,
}: SkeletonProps) {
  const classes = [styles.skeleton, className].filter(Boolean).join(" ");
  return (
    <span
      aria-hidden="true"
      className={classes}
      style={{
        width,
        height,
        ...(radius === undefined ? {} : { borderRadius: radius }),
      }}
    />
  );
}
