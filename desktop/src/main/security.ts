/**
 * Security helpers for the Electron main process.
 *
 * Extracted into a separate module for testability.
 * All functions are pure and have no side effects.
 */

import * as path from "path";
import { app } from "electron";

/** Expected Vite dev server origin (exact match, no startsWith). */
export const DEV_ORIGIN = "http://localhost:5173";

/**
 * Validate that a URL string has the exact expected origin.
 * Uses URL parsing — never startsWith.
 */
export function hasExactOrigin(targetUrl: string, expectedOrigin: string): boolean {
  try {
    const parsed = new URL(targetUrl);
    return parsed.origin === expectedOrigin;
  } catch {
    return false;
  }
}

/**
 * Validate that the sender's URL is an expected origin.
 * - Development: exact http://localhost:5173 origin.
 * - Packaged mode: fails closed (Stage 3 packaging deferred).
 */
export function isValidOrigin(senderUrl: string): boolean {
  if (!app.isPackaged) {
    return hasExactOrigin(senderUrl, DEV_ORIGIN);
  }
  // Packaged mode: fail closed. Stage 3 packaging is deferred.
  return false;
}

/**
 * Validate that a navigation URL is allowed.
 * - Development: exact http://localhost:5173 origin.
 * - Packaged mode: fails closed.
 */
export function isAllowedNavigation(targetUrl: string): boolean {
  if (!app.isPackaged) {
    return hasExactOrigin(targetUrl, DEV_ORIGIN);
  }
  // Packaged mode: fail closed.
  return false;
}

/**
 * Resolve the repository root directory.
 *
 * In development, the compiled main process is at:
 *   desktop/dist-electron/main/index.js
 *
 * We need to resolve to the repository root (parent of desktop/),
 * so Python receives PYTHONPATH=<repo>/src.
 *
 * Strategy:
 * - In development: use app.getAppPath() which returns the desktop/ dir,
 *   then resolve its parent.
 * - Fallback: use __dirname and navigate up from dist-electron/main/.
 */
export function resolveRepoRoot(): string {
  if (!app.isPackaged) {
    // app.getAppPath() returns the directory containing package.json,
    // which is desktop/ in development.
    const appPath = app.getAppPath();
    return path.resolve(appPath, "..");
  }
  // Packaged mode should fail closed — this path should never be reached.
  return path.resolve(__dirname, "..", "..", "..");
}

/**
 * Compute the PYTHONPATH for the Python backend.
 * Always resolves to <repo>/src.
 */
export function resolvePythonPath(): string {
  return path.join(resolveRepoRoot(), "src");
}

/**
 * Resolve the compiled preload path.
 *
 * The main process compiles to dist-electron/main/index.js.
 * The preload compiles to dist-electron/preload/index.js (sibling of main/).
 *
 * This function returns the correct path regardless of whether the code
 * is running from source (TypeScript) or compiled (JavaScript).
 */
export function resolvePreloadPath(): string {
  // __dirname is dist-electron/main/ after compilation.
  // The preload is at dist-electron/preload/index.js.
  return path.join(__dirname, "..", "preload", "index.js");
}
