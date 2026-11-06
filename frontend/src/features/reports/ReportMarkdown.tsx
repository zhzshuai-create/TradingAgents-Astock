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
        remarkPlugins={[remarkGfm]}
        components={mobile ? MOBILE_COMPONENTS : DESKTOP_COMPONENTS}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
