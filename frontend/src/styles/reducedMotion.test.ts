import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(process.cwd(), "src");
const GLOBAL = join(SRC, "styles", "global.css");
const REDUCE = "@media (prefers-reduced-motion: reduce)";

function sourceFiles(directory: string, pattern: RegExp): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...sourceFiles(path, pattern));
    } else if (pattern.test(entry.name)) {
      files.push(path);
    }
  }
  return files;
}

const cssFiles = sourceFiles(SRC, /\.css$/);
const codeFiles = sourceFiles(SRC, /\.(ts|tsx)$/).filter(
  (file) => !/\.test\.tsx?$/.test(file),
);

function read(file: string): string {
  return readFileSync(file, "utf8");
}

function relative(file: string): string {
  return file.slice(SRC.length + 1).split("\\").join("/");
}

function reduceBlock(file: string): string {
  const css = read(file);
  const start = css.indexOf(REDUCE);
  expect(start, `${relative(file)} has no reduced-motion block`).toBeGreaterThan(
    -1,
  );
  return css.slice(start);
}

describe("RM-01 reduced motion", () => {
  it("caps animation and transition duration for every element", () => {
    const block = reduceBlock(GLOBAL);
    expect(block).toMatch(/\*,\s*\*::before,\s*\*::after/);
    expect(block).toMatch(/animation-duration:\s*0\.01ms\s*!important/);
    expect(block).toMatch(/animation-iteration-count:\s*1\s*!important/);
    expect(block).toMatch(/transition-duration:\s*0\.01ms\s*!important/);
  });

  it("keeps the only infinite animation behind its own opt-out", () => {
    const loops = cssFiles.filter((file) => read(file).includes("infinite"));
    expect(loops.map(relative)).toEqual(["ui/Skeleton.module.css"]);
    expect(reduceBlock(loops[0])).toMatch(/animation:\s*none/);
  });

  it("declares no animation inline in components", () => {
    const offenders = codeFiles.filter((file) =>
      /\banimation(Name)?:\s*["'][^"']+["']/.test(read(file)),
    );
    expect(offenders.map(relative)).toEqual([]);
  });
});

describe("RM-02 smooth scrolling follows the preference", () => {
  it("never sets scroll-behavior: smooth in styles", () => {
    const offenders = cssFiles.filter((file) =>
      /scroll-behavior:\s*smooth/.test(read(file)),
    );
    expect(offenders.map(relative)).toEqual([]);
    expect(read(GLOBAL)).toMatch(/scroll-behavior:\s*auto\s*!important/);
  });

  it("guards every smooth scroll call with the media query", () => {
    const smooth = codeFiles.filter((file) => read(file).includes('"smooth"'));
    expect(smooth.map(relative)).toEqual(["features/jobs/JobDetailPage.tsx"]);
    for (const file of smooth) {
      expect(read(file), relative(file)).toContain("prefers-reduced-motion");
    }
  });

  it("uses no scrollTo or scrollBy with a smooth behavior", () => {
    const offenders = codeFiles.filter((file) =>
      /scroll(To|By)\([\s\S]*?"smooth"/.test(read(file)),
    );
    expect(offenders.map(relative)).toEqual([]);
  });
});

describe("RM-03 entry animations inherit the global rule", () => {
  it("keeps dialog, drawer, toast and market transitions one-shot", () => {
    for (const file of [
      "ui/Dialog.module.css",
      "ui/Drawer.module.css",
      "ui/Toast.module.css",
      "features/market/MarketPage.module.css",
    ]) {
      const css = read(join(SRC, file));
      expect(css, file).toMatch(/animation:/);
      expect(css, file).not.toContain("infinite");
    }
  });
});
