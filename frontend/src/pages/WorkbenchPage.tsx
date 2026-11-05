import { useState } from "react";

import { Button, Dialog } from "../ui";
import { Placeholder } from "./Placeholder";

export function WorkbenchPage() {
  const [launcherOpen, setLauncherOpen] = useState(false);

  return (
    <>
      <Placeholder
        title="工作台"
        description="分析启动器与市场摘要将在 P3 接入。现在可以先用顶部搜索打开股票工作区。"
        testId="page-workbench"
        action={
          <Button
            variant="primary"
            data-testid="workbench-primary"
            onClick={() => setLauncherOpen(true)}
          >
            开始分析一只股票
          </Button>
        }
      />
      <Dialog
        open={launcherOpen}
        title="分析启动器"
        onClose={() => setLauncherOpen(false)}
        footer={
          <Button variant="primary" onClick={() => setLauncherOpen(false)}>
            知道了
          </Button>
        }
      >
        <p>
          分析启动器将在 P3 接入。当前版本只提供导航与页面骨架，不会创建任务或消耗额度。
        </p>
      </Dialog>
    </>
  );
}
