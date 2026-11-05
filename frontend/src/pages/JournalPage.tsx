import { Link } from "react-router-dom";

import { Placeholder } from "./Placeholder";
import styles from "./pages.module.css";

export function JournalPage() {
  return (
    <Placeholder
      title="交易日志"
      description="交易日志暂不可用：记录功能尚未接入。下一步可以回到工作台发起一次分析。"
      testId="page-journal"
      action={
        <Link className={styles.textLink} to="/workbench">
          回工作台
        </Link>
      }
    />
  );
}
