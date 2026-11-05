import { useParams } from "react-router-dom";

import { Placeholder } from "./Placeholder";

export function ReportDetailPage() {
  const { reportId = "" } = useParams();

  return (
    <Placeholder
      title={`报告 ${reportId}`}
      description="报告阅读器、导出与重新分析将在 P5 接入。"
      testId="page-report-detail"
    />
  );
}
