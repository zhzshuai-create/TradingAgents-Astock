import { useParams } from "react-router-dom";

import { Placeholder } from "./Placeholder";

export function JobDetailPage() {
  const { jobId = "" } = useParams();

  return (
    <Placeholder
      title={`任务 ${jobId}`}
      description="阶段时间线、阶段报告与任务控制将在 P4 接入。"
      testId="page-job-detail"
    />
  );
}
