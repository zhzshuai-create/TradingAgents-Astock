import { useNavigate, useParams } from "react-router-dom";

import { Button } from "../ui";
import { InvalidTickerPage } from "./InvalidTickerPage";
import { Placeholder } from "./Placeholder";

const TICKER_PATTERN = /^\d{6}$/;

export function StockPage() {
  const { ticker = "" } = useParams();
  const navigate = useNavigate();

  if (!TICKER_PATTERN.test(ticker)) {
    return <InvalidTickerPage ticker={ticker} />;
  }

  return (
    <Placeholder
      title={`${ticker} 股票工作区`}
      description="行情快照、K 线、分时与新闻将在 P3 接入。"
      testId="page-stock"
      action={
        <Button
          variant="primary"
          onClick={() =>
            navigate(`/workbench?launch=1&ticker=${ticker}`)
          }
        >
          开始分析
        </Button>
      }
    />
  );
}
