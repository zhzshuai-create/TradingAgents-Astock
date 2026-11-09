import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dev API entry (scripts/dev_backend.py) listens on 8600 by default.
// E2E runs pass VITE_API_PROXY_TARGET so the preview server can reach a
// backend on a temporary port without changing the build.
const apiTarget =
  process.env.VITE_API_PROXY_TARGET?.trim() || "http://127.0.0.1:8600";

export default defineConfig({
  plugins: [react()],
  build: {
    // scripts/check_bundle.mjs reads the manifest to prove one chunk per route.
    manifest: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": apiTarget,
    },
  },
  preview: {
    proxy: {
      "/api": apiTarget,
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    // Report fixtures carry +08:00 stamps and assertions read Beijing wall
    // time; CI runners default to UTC and would render 01:04 instead of 09:04.
    env: { TZ: "Asia/Shanghai" },
  },
});
