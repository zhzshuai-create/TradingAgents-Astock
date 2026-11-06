import { useParams } from "react-router-dom";

import { StockPage as StockWorkspace } from "../features/stocks/StockPage";
import { isTickerFormat } from "../features/stocks/stockParams";
import { InvalidTickerPage } from "./InvalidTickerPage";

/** Route shell: keeps `page-stock` on the workspace, 400s the path shape. */
export function StockPage() {
  const { ticker = "" } = useParams();

  if (!isTickerFormat(ticker)) {
    return <InvalidTickerPage ticker={ticker} />;
  }

  return <StockWorkspace ticker={ticker} />;
}
