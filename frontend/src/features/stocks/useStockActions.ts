import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import type { JobDetail, JobSummary } from "../../api/types";
import { stockActiveJobQuery } from "../../lib/query";
import type { TickerSelection } from "../launcher/types";
import { ACTIVE_JOB_STATUSES } from "../../shell/useActiveJobs";

export interface StockActions {
  activeJob: JobSummary | null;
  launcherOpen: boolean;
  initialTicker: TickerSelection;
  openLauncher: () => void;
  closeLauncher: () => void;
  created: (job: JobDetail) => void;
  primary: { label: string; onClick: () => void };
}

/** D7 head actions: analyze, or jump to the one active job for this ticker. */
export function useStockActions(ticker: string, name: string | null): StockActions {
  const navigate = useNavigate();
  const [launcherOpen, setLauncherOpen] = useState(false);
  const active = useQuery(stockActiveJobQuery(ticker));
  const first = active.data?.items[0] ?? null;
  const activeJob =
    first !== null && ACTIVE_JOB_STATUSES.includes(first.status) ? first : null;

  function openLauncher() {
    setLauncherOpen(true);
  }

  function created(job: JobDetail) {
    setLauncherOpen(false);
    navigate(`/jobs/${job.job_id}`, { replace: true });
  }

  const primary =
    activeJob === null
      ? { label: "分析这只股票", onClick: openLauncher }
      : {
          label: "查看进行中任务",
          onClick: () => navigate(`/jobs/${activeJob.job_id}`),
        };

  return {
    activeJob,
    launcherOpen,
    initialTicker: { code: ticker, name },
    openLauncher,
    closeLauncher: () => setLauncherOpen(false),
    created,
    primary,
  };
}
