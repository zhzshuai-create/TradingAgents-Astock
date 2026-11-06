#!/usr/bin/env node
/**
 * DS-08: prove the P4 route split stayed inside the bundle budget.
 *
 * Reads Vite's build manifest, so a page that silently merges back into the
 * entry chunk fails here even if the total is small. Run after `vite build`.
 *
 *   node scripts/check_bundle.mjs [--out <path>]
 */

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const FRONTEND = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const DIST = path.join(FRONTEND, "dist");
const MANIFEST = path.join(DIST, ".vite", "manifest.json");
const DEFAULT_OUT = path.join(
  FRONTEND,
  "..",
  "docs",
  "upgrade",
  "reviews",
  "2026-11-06_P4-04拆包结果.json",
);

const BASELINE_ENTRY_KB = 202.45;
const ROUTE_CHUNK_LIMIT_KB = 60;

const ROUTE_SOURCES = [
  "src/features/workbench/WorkbenchPage.tsx",
  "src/pages/MarketPage.tsx",
  "src/pages/StockPage.tsx",
  "src/pages/InvalidTickerPage.tsx",
  "src/pages/JobsPage.tsx",
  "src/pages/JobDetailPage.tsx",
  "src/pages/ReportsPage.tsx",
  "src/pages/ReportDetailPage.tsx",
  "src/pages/JournalPage.tsx",
  "src/pages/SettingsPage.tsx",
  "src/pages/NotFoundPage.tsx",
];

function outPath() {
  const index = process.argv.indexOf("--out");
  return index === -1 ? DEFAULT_OUT : path.resolve(process.argv[index + 1]);
}

function gzipKb(file) {
  const bytes = readFileSync(path.join(DIST, file));
  return Number((gzipSync(bytes, { level: 9 }).length / 1000).toFixed(2));
}

const manifest = JSON.parse(readFileSync(MANIFEST, "utf8"));
const entries = Object.entries(manifest);

const entryEntries = entries.filter(([, chunk]) => chunk.isEntry);
if (entryEntries.length !== 1) {
  throw new Error(`expected one entry chunk, found ${entryEntries.length}`);
}
const [entrySource, entryChunk] = entryEntries[0];
const entryKb = gzipKb(entryChunk.file);

const routeChunks = ROUTE_SOURCES.map((source) => {
  const chunk = manifest[source];
  if (chunk === undefined) {
    throw new Error(`route source missing from manifest: ${source}`);
  }
  const dynamic = (entryChunk.dynamicImports ?? []).includes(source);
  const kb = gzipKb(chunk.file);
  return {
    source,
    file: chunk.file,
    gzip_kb: kb,
    dynamic_import: dynamic,
    separate_from_entry: chunk.file !== entryChunk.file,
    within_60_kb: kb <= ROUTE_CHUNK_LIMIT_KB,
  };
});

const routeFiles = new Set(routeChunks.map((chunk) => chunk.file));
const sharedChunks = entries
  .filter(([, chunk]) => chunk.file.endsWith(".js"))
  .filter(([, chunk]) => chunk.file !== entryChunk.file)
  .filter(([, chunk]) => !routeFiles.has(chunk.file))
  .map(([source, chunk]) => ({
    source,
    file: chunk.file,
    gzip_kb: gzipKb(chunk.file),
  }));

const entryOk = entryKb <= BASELINE_ENTRY_KB;
const routesOk = routeChunks.every(
  (chunk) =>
    chunk.dynamic_import && chunk.separate_from_entry && chunk.within_60_kb,
);

const evidence = {
  ticket: "P4-04",
  command: "npm run build && node scripts/check_bundle.mjs",
  measured_with: "node:zlib gzipSync level 9 over dist files",
  baseline_entry_gzip_kb: BASELINE_ENTRY_KB,
  entry: {
    source: entrySource,
    file: entryChunk.file,
    gzip_kb: entryKb,
    within_budget: entryOk,
  },
  route_chunk_limit_gzip_kb: ROUTE_CHUNK_LIMIT_KB,
  route_chunks: routeChunks,
  route_chunks_within_budget: routesOk,
  shared_chunks: sharedChunks,
  passed: entryOk && routesOk,
};

const target = outPath();
writeFileSync(target, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");

console.log(`entry ${entryKb} kB gzip (limit ${BASELINE_ENTRY_KB})`);
for (const chunk of routeChunks) {
  console.log(
    `${chunk.dynamic_import ? "lazy" : "STATIC"} ${chunk.file} ${chunk.gzip_kb} kB`,
  );
}
console.log(`evidence: ${target}`);

if (!evidence.passed) {
  console.error("bundle budget failed");
  process.exit(1);
}
