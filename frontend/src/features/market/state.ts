import type { MarketEnvelope } from "../../api/types";
import type { DataStateValue } from "./copy";

interface EnvelopeQuery<T> {
  isPending: boolean;
  isError: boolean;
  data: MarketEnvelope<T> | undefined;
}

/** Maps a query result onto the five DataState values (partial stays a flag). */
export function envelopeState<T>(query: EnvelopeQuery<T>): DataStateValue {
  if (query.isPending) {
    return "loading";
  }
  if (query.isError || query.data === undefined) {
    return "error";
  }
  return query.data.status;
}