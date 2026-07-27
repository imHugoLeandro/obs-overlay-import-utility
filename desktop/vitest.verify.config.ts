/**
 * Vitest configuration for compiled-output verification.
 *
 * This config is used by `npm run verify:compiled` and runs ONLY the
 * compiled-output test suite.  It must be executed AFTER `npm run build`
 * so that dist-electron/ and dist/ artifacts exist.
 *
 * Unlike the default vitest config (vite.config.ts), this config does
 * NOT exclude compiled-output.test.ts — that is its sole purpose.
 */

import { defineConfig } from "vitest/config";
import { resolve } from "path";

export default defineConfig({
  test: {
    globals: true,
    environment: "node",
    include: [resolve(__dirname, "tests/compiled-output.test.ts")],
    setupFiles: [],
    css: false,
  },
});
