/** Server-owned options for the launcher and settings page (api-v1.md 1.8). */

import { apiRequest } from "./client";
import type { MetaOptions } from "./types";

export function getMetaOptions(signal?: AbortSignal): Promise<MetaOptions> {
  return apiRequest<MetaOptions>("/api/v1/meta/options", { signal });
}
