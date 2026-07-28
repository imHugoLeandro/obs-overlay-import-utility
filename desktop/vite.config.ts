import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

const srcRoot = resolve(__dirname, "src/renderer");

// https://vitejs.dev/config
export default defineConfig({
  root: srcRoot,
  plugins: [react()],
  base: "./",
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: resolve(__dirname, "dist"),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: resolve(srcRoot, "index.html"),
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: [resolve(__dirname, "tests/setup.ts")],
    include: [
      resolve(__dirname, "tests/**/*.test.ts"),
      resolve(__dirname, "tests/**/*.test.tsx"),
    ],
    exclude: [
      // Compiled-output verification runs only via `npm run verify:compiled`
      // after `npm run build`.  It must not run as part of `npm test`.
      resolve(__dirname, "tests/compiled-output.test.ts"),
      // Electron integration smoke test runs only via `npm run test:integration`
      // which requires Xvfb and a display.  It must not run as part of `npm test`.
      resolve(__dirname, "tests/integration.test.ts"),
    ],
    css: true,
  },
});
