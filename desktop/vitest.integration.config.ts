/**
 * Vitest configuration for Electron integration smoke tests.
 *
 * Runs ONLY the integration test suite.  Requires Xvfb and a built
 * Electron app (dist-electron/ and dist/).
 */

import { defineConfig } from "vitest/config";
import { resolve } from "path";
import { toVitestGlob } from "./vitest-paths";

export default defineConfig({
  test: {
    globals: true,
    environment: "node",
    include: [toVitestGlob(resolve(__dirname, "tests/integration.test.ts"))],
    setupFiles: [],
    css: false,
    testTimeout: 60000,
    hookTimeout: 30000,
  },
});
