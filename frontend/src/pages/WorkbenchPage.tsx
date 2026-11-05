import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Button, Dialog } from "../ui";
import { Placeholder } from "./Placeholder";

const CODE_PATTERN = /^\d{6}$/;

export function WorkbenchPage() {
  const [params, setParams] = useSearchParams();
  const requested =
    params.get("launch") === "1" ? (params.get("ticker") ?? "") : "";
  const launchTicker = CODE_PATTERN.test(requested) ? requested : "";
  const [launcherOpen, setLauncherOpen] = useState(launchTicker !== "");

  useEffect(() => {
    if (launchTicker !== "") {
      setLauncherOpen(true);
    }
  }, [launchTicker]);

  function closeLauncher() {
    setLauncherOpen(false);
    if (params.has("launch") || params.has("ticker")) {
      setParams({}, { replace: true });
    }
  }

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
        onClose={closeLauncher}
        footer={
          <Button variant="primary" onClick={closeLauncher}>
            知道了
          </Button>
        }
      >
        <p>
          {launchTicker
            ? `已选择股票 ${launchTicker}。`
            : "分析启动器将在 P3 接入。"}
          当前版本只提供导航与页面骨架，不会创建任务或消耗额度。
        </p>
      </Dialog>
    </>
  );
}
