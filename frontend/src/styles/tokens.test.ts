import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(process.cwd(), "src");
const TOKENS = join(SRC, "styles", "tokens.css");

function sourceFiles(directory: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...sourceFiles(path));
    } else if (/\.(ts|tsx|css)$/.test(entry.name)) {
      files.push(path);
    }
  }
  return files;
}

describe("WEB-01 设计令牌", () => {
  it("tokens.css 覆盖颜色、间距、字号、圆角、断点五组", () => {
    const css = readFileSync(TOKENS, "utf8");
    expect(css).toMatch(/--color-text-primary:/);
    expect(css).toMatch(/--space-6:/);
    expect(css).toMatch(/--font-size-md:/);
    expect(css).toMatch(/--radius-md:/);
    expect(css).toMatch(/--bp-md:\s*\d+px/);
  });

  it("亮暗两套语义颜色都在 tokens.css 里", () => {
    const css = readFileSync(TOKENS, "utf8");
    expect(css).toContain(':root[data-theme="dark"]');
    expect(css).toContain("prefers-color-scheme: dark");
    expect(css).toMatch(/--color-bg-canvas:/);
  });

  it("除 tokens.css 外不出现十六进制色值", () => {
    const hex = /#[0-9a-fA-F]{3,8}\b/;
    const offenders = sourceFiles(SRC)
      .filter((file) => file !== TOKENS)
      .filter((file) => hex.test(readFileSync(file, "utf8")))
      .map((file) => file.slice(SRC.length + 1));
    expect(offenders).toEqual([]);
  });
});
