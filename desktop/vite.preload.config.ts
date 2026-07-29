import { defineConfig } from "vite";
import { resolve } from "node:path";

/**
 * Bundle the sandboxed preload into exactly one CommonJS file. Electron stays
 * external because sandboxed preloads may require Electron's supported API,
 * while every local shared module is inlined into this artifact.
 */
export default defineConfig({
  build: {
    outDir: resolve(__dirname, "dist-electron", "preload"),
    emptyOutDir: true,
    lib: {
      entry: resolve(__dirname, "src", "preload", "index.ts"),
      formats: ["cjs"],
      fileName: () => "index.js",
    },
    rollupOptions: {
      external: ["electron"],
      output: {
        format: "cjs",
        entryFileNames: "index.js",
        inlineDynamicImports: true,
      },
    },
  },
});
