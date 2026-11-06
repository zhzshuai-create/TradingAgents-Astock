/**
 * The only markdown renderer in the reader. Raw HTML is dropped (skipHtml) and
 * react-markdown's default URL transform removes javascript:/data: targets, so
 * stored text cannot execute. External links open in a new tab with rel set;
 * wide tables scroll inside their own container instead of the page.
 */

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import styles from "./ReportMarkdown.module.css";

function isExternal(href: string | undefined): boolean {
  return typeof href === "string" && /^https?:\/\//i.test(href);
}

const components: Components = {
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
  table({ children, node: _node, ...rest }) {
    return (
      <div className={styles.tableWrap}>
        <table {...rest}>{children}</table>
      </div>
    );
  },
};

export function ReportMarkdown({ children }: { children: string }) {
  return (
    <div className={styles.prose}>
      <ReactMarkdown skipHtml remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
