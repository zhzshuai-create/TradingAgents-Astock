/** Small display helpers shared by the job list and the detail page. */

export interface MarkdownPreview {
  text: string;
  hasMore: boolean;
}

/** Cut a long stage report to a short preview without splitting a line. */
export function markdownPreview(
  markdown: string,
  maxLines = 12,
  maxChars = 1200,
): MarkdownPreview {
  const lines = markdown.split("\n");
  let text = "";
  for (let index = 0; index < lines.length; index += 1) {
    const next = text === "" ? lines[index] : `${text}\n${lines[index]}`;
    if (next.length > maxChars || index >= maxLines) {
      return { text: text === "" ? next.slice(0, maxChars) : text, hasMore: true };
    }
    text = next;
  }
  return { text, hasMore: false };
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) {
    return "—";
  }
  if (ms < 1000) {
    return `${Math.round(ms)} 毫秒`;
  }
  const totalSeconds = Math.floor(ms / 1000);
  if (totalSeconds < 60) {
    return `${totalSeconds} 秒`;
  }
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) {
    return seconds === 0 ? `${minutes} 分钟` : `${minutes} 分 ${seconds} 秒`;
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} 小时` : `${hours} 小时 ${rest} 分`;
}
