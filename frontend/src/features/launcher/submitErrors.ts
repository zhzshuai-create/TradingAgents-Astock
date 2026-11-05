import type { ApiError } from "../../api/errors";

export interface TickerCandidate {
  code: string;
  name: string;
}

export interface SubmitFieldErrors {
  fields: {
    ticker?: string;
    analysis_date?: string;
    llm_profile?: string;
    config?: string;
  };
  candidates: TickerCandidate[];
  allowedValues: string[];
}

const EMPTY: SubmitFieldErrors = { fields: {}, candidates: [], allowedValues: [] };

function strings(raw: unknown): string[] {
  return Array.isArray(raw)
    ? raw.filter((item): item is string => typeof item === "string")
    : [];
}

function candidates(raw: unknown): TickerCandidate[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.flatMap((item) => {
    if (typeof item !== "object" || item === null) {
      return [];
    }
    const record = item as Record<string, unknown>;
    if (typeof record.code !== "string") {
      return [];
    }
    return [
      { code: record.code, name: typeof record.name === "string" ? record.name : record.code },
    ];
  });
}

/** Maps a create failure onto form fields; anything else stays a banner. */
export function fieldErrorsFor(error: ApiError | null): SubmitFieldErrors {
  if (error === null) {
    return EMPTY;
  }
  const allowedValues = strings(error.details.allowed_values);
  const picked = candidates(error.details.candidates);

  switch (error.code) {
    case "ticker_unresolved":
    case "ticker_ambiguous":
      return {
        fields: { ticker: error.message },
        candidates: picked,
        allowedValues: [],
      };
    case "invalid_date":
      return { fields: { analysis_date: error.message }, candidates: [], allowedValues: [] };
    case "config_unknown_key":
    case "config_invalid_value": {
      const field =
        typeof error.details.field === "string" ? error.details.field : "";
      return {
        fields:
          field === "llm_profile"
            ? { llm_profile: error.message }
            : { config: error.message },
        candidates: [],
        allowedValues,
      };
    }
    case "invalid_request": {
      const field =
        typeof error.details.field === "string" ? error.details.field : "";
      if (field === "ticker") {
        return { fields: { ticker: error.message }, candidates: [], allowedValues: [] };
      }
      if (field === "analysis_date") {
        return {
          fields: { analysis_date: error.message },
          candidates: [],
          allowedValues: [],
        };
      }
      if (field === "llm_profile") {
        return {
          fields: { llm_profile: error.message },
          candidates: [],
          allowedValues,
        };
      }
      if (field === "config") {
        return { fields: { config: error.message }, candidates: [], allowedValues };
      }
      return EMPTY;
    }
    default:
      return EMPTY;
  }
}

export function hasFieldErrors(errors: SubmitFieldErrors): boolean {
  return Object.keys(errors.fields).length > 0;
}
