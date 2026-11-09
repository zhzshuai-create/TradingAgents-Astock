/**
 * The only markdown renderer in the reader. Raw HTML is dropped (skipHtml) and
 * react-markdown's default URL transform removes javascript:/data: targets, so
 * stored text cannot execute. External links open in a new tab with rel set;
 * wide tables scroll inside their own container instead of the page. Below the
 * mobile breakpoint tables are rendered as stacked cards, not tables (M06).
 */

import type { Element, ElementContent } from "hast";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import styles from "./ReportMarkdown.module.css";

type MdNode = {
  type: string;
  value?: string;
  children?: MdNode[];
};

// CommonMark flanking rules reject `**` glued between CJK text and punctuation
// (e.g. 属于**“…”形态**。), leaving the markers literal. Mark just those pairs
// with private-use characters before parsing, then turn the markers into strong
// nodes. Stored markdown and content hashes are never modified.
const BOLD_OPEN = "\uE000";
const BOLD_CLOSE = "\uE001";
const PUNCTUATION = /[\p{P}\p{S}]/u;
const WHITESPACE = /\s/u;

function leftFlanking(first: string, before: string): boolean {
  if (WHITESPACE.test(first)) {
    return false;
  }
  return (
    !PUNCTUATION.test(first) ||
    before === "" ||
    WHITESPACE.test(before) ||
    PUNCTUATION.test(before)
  );
}

function rightFlanking(last: string, after: string): boolean {
  if (WHITESPACE.test(last)) {
    return false;
  }
  return (
    !PUNCTUATION.test(last) ||
    after === "" ||
    WHITESPACE.test(after) ||
    PUNCTUATION.test(after)
  );
}

function repairLine(line: string, codeRanges: Array<[number, number]>): string {
  const pair = /\*\*([^*\n]+?)\*\*/g;
  return line.replace(pair, (match, content: string, offset: number) => {
    const first = content[0] ?? "";
    const last = content[content.length - 1] ?? "";
    if (!content.trim() || /[`[\]<>]/.test(content)) {
      return match;
    }
    if (codeRanges.some(([start, end]) => offset >= start && offset < end)) {
      return match;
    }
    const before = line[offset - 1] ?? "";
    const after = line[offset + match.length] ?? "";
    if (leftFlanking(first, before) && rightFlanking(last, after)) {
      return match;
    }
    return `${BOLD_OPEN}${content}${BOLD_CLOSE}`;
  });
}

function normalizeBold(markdown: string): string {
  let fenced = false;
  return markdown
    .split("\n")
    .map((line) => {
      const head = line.trimStart();
      if (head.startsWith("```") || head.startsWith("~~~")) {
        fenced = !fenced;
        return line;
      }
      if (fenced || /^(\t| {4})/.test(line)) {
        return line;
      }
      const codeRanges: Array<[number, number]> = [];
      const code = /(`+)[\s\S]*?\1/g;
      let match: RegExpExecArray | null;
      while ((match = code.exec(line)) !== null) {
        codeRanges.push([match.index, match.index + match[0].length]);
      }
      return repairLine(line, codeRanges);
    })
    .join("\n");
}

function splitMarkedBold(value: string): MdNode[] | null {
  const nodes: MdNode[] = [];
  let cursor = 0;
  while (true) {
    const open = value.indexOf(BOLD_OPEN, cursor);
    if (open === -1) {
      break;
    }
    const close = value.indexOf(BOLD_CLOSE, open + 1);
    if (close === -1) {
      break;
    }
    if (open > cursor) {
      nodes.push({ type: "text", value: value.slice(cursor, open) });
    }
    nodes.push({
      type: "strong",
      children: [{ type: "text", value: value.slice(open + 1, close) }],
    });
    cursor = close + 1;
  }
  if (nodes.length === 0) {
    return null;
  }
  if (cursor < value.length) {
    nodes.push({ type: "text", value: value.slice(cursor) });
  }
  return nodes;
}

function rewriteBold(node: MdNode): void {
  if (!node.children) {
    return;
  }
  const next: MdNode[] = [];
  for (const child of node.children) {
    const replaced =
      child.type === "text" && typeof child.value === "string"
        ? splitMarkedBold(child.value)
        : null;
    if (replaced) {
      next.push(...replaced);
    } else {
      rewriteBold(child);
      next.push(child);
    }
  }
  node.children = next;
}

function remarkCjkBold() {
  return (tree: MdNode): void => rewriteBold(tree);
}

function isExternal(href: string | undefined): boolean {
  return typeof href === "string" && /^https?:\/\//i.test(href);
}

function textOf(node: ElementContent): string {
  if (node.type === "text") {
    return node.value;
  }
  if (node.type === "element") {
    return node.children.map(textOf).join("");
  }
  return "";
}

function tableRows(element: Element): string[][] {
  return element.children
    .filter(
      (child): child is Element =>
        child.type === "element" && child.tagName === "tr",
    )
    .map((row) =>
      row.children
        .filter(
          (cell): cell is Element =>
            cell.type === "element" &&
            (cell.tagName === "td" || cell.tagName === "th"),
        )
        .map((cell) => textOf(cell).trim()),
    );
}

function tableData(node: Element | undefined): {
  header: string[];
  rows: string[][];
} {
  const header: string[] = [];
  const rows: string[][] = [];
  for (const child of node?.children ?? []) {
    if (child.type !== "element") {
      continue;
    }
    if (child.tagName === "thead") {
      header.push(...(tableRows(child)[0] ?? []));
    } else if (child.tagName === "tbody") {
      rows.push(...tableRows(child));
    }
  }
  return { header, rows };
}

/** Mobile summary card per table row; header cells become the labels. */
function MobileTable({ node }: { node: Element | undefined }) {
  const { header, rows } = tableData(node);
  if (rows.length === 0) {
    return null;
  }
  return (
    <div className={styles.tableView} data-testid="markdown-table-cards">
      {rows.map((cells, rowIndex) => (
        <dl className={styles.tableCard} key={rowIndex}>
          {cells.map((value, cellIndex) => (
            <div className={styles.tableCardRow} key={cellIndex}>
              <dt>{header[cellIndex] ?? `列 ${cellIndex + 1}`}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      ))}
    </div>
  );
}

const linkAndImage: Components = {
  a({ href, children, node: _node, ...rest }) {
    if (isExternal(href)) {
      return (
        <a {...rest} href={href} target="_blank" rel="noopener noreferrer">
          {children}
        </a>
      );
    }
    return (
      <a {...rest} href={href}>
        {children}
      </a>
    );
  },
  img({ src, alt, node: _node, ...rest }) {
    // A stripped data: URL would leave an empty <img>; keep only fetchable
    // http(s) sources and fall back to the alt text otherwise.
    if (!isExternal(src)) {
      return alt ? <span>{alt}</span> : null;
    }
    return <img {...rest} src={src} alt={alt ?? ""} />;
  },
};

function buildComponents(mobile: boolean): Components {
  return {
    ...linkAndImage,
    table({ children, node, ...rest }) {
      if (mobile) {
        return <MobileTable node={node} />;
      }
      return (
        <div className={styles.tableWrap}>
          <table {...rest}>{children}</table>
        </div>
      );
    },
    // GFM header cells carry no scope; the mobile card path drops tables.
    th({ children, ...rest }) {
      return (
        <th {...rest} scope="col">
          {children}
        </th>
      );
    },
  };
}

const DESKTOP_COMPONENTS = buildComponents(false);
const MOBILE_COMPONENTS = buildComponents(true);

export function ReportMarkdown({
  children,
  mobile = false,
}: {
  children: string;
  mobile?: boolean;
}) {
  return (
    <div className={styles.prose}>
      <ReactMarkdown
        skipHtml
        remarkPlugins={[remarkGfm, remarkCjkBold]}
        components={mobile ? MOBILE_COMPONENTS : DESKTOP_COMPONENTS}
      >
        {normalizeBold(children)}
      </ReactMarkdown>
    </div>
  );
}
