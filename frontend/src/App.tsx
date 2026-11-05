import styles from "./App.module.css";
import { Badge } from "./ui";

export default function App() {
  return (
    <main className={styles.page}>
      <Badge tone="info">P2-01</Badge>
      <h1 className={styles.title}>AStock Pro</h1>
      <p className={styles.lead}>
        分析任务中心的前端工程与设计令牌已就绪，外壳与路由将在下一步接入。
      </p>
    </main>
  );
}
