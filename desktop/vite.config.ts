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
    css: true,
  },
});
