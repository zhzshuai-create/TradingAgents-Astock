import { Skeleton } from "../ui/Skeleton";
import styles from "./PageFallback.module.css";

/** Suspense fallback: same width and rhythm as a first-screen page block. */
export function PageFallback() {
  return (
    <div
      className={styles.page}
      data-testid="route-fallback"
      aria-busy="true"
      aria-label="页面加载中"
    >
      <Skeleton width="6rem" height="0.75rem" />
      <Skeleton width="min(320px, 60%)" height="2rem" />
      <Skeleton width="min(560px, 90%)" height="1rem" />
      <Skeleton width="100%" height="10rem" radius="var(--radius-lg)" />
    </div>
  );
}
