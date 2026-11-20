// SPDX-License-Identifier: Apache-2.0
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/patchtrail/web/dist", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8470" } },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test-setup.ts"] },
});
