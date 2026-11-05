import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dev API entry (scripts/dev_backend.py) listens on 8600 by default.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8600",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
  },
});
