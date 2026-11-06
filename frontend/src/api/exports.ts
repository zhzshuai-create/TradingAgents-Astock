/** Export endpoints from api-v1.md 2.4-2.5. */

import { apiRequest, apiRequestEnvelope, resolveUrl } from "./client";
import type { ExportState, ExportStatus } from "./types";

export const PDF_EXPORT_TEMPLATE = "default";

export interface PdfExportRequest {
  exportId: string;
  status: ExportState;
  pollUrl: string;
  cached: boolean;
}

interface PdfExportCreated {
  export_id: string;
  status: ExportState;
  poll_url: string;
}

export async function requestPdfExport(
  reportId: string,
): Promise<PdfExportRequest> {
  const envelope = await apiRequestEnvelope<PdfExportCreated>(
    `/api/v1/reports/${encodeURIComponent(reportId)}/exports/pdf`,
    { method: "POST", body: { template: PDF_EXPORT_TEMPLATE } },
  );
  return {
    exportId: envelope.data.export_id,
    status: envelope.data.status,
    pollUrl: envelope.data.poll_url,
    cached: envelope.headers.get("X-Export-Cached") === "1",
  };
}

export function getExportStatus(
  exportId: string,
  signal?: AbortSignal,
): Promise<ExportStatus> {
  return apiRequest<ExportStatus>(
    `/api/v1/exports/${encodeURIComponent(exportId)}`,
    { signal },
  );
}

/** The only place the client turns an export id into a download URL. */
export function exportFileUrl(exportId: string): string {
  return resolveUrl(`/api/v1/exports/${encodeURIComponent(exportId)}/file`);
}
