/**
 * Tests for the security helpers extracted from the Electron main process.
 *
 * Tests:
 * - Exact development-origin validation (no startsWith)
 * - Navigation validation
 * - Repository/PYTHONPATH resolution
 * - Compiled preload path
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import * as path from "path";

// Mock Electron's app module using vi.hoisted to avoid hoisting issues.
const mockApp = vi.hoisted(() => ({
  isPackaged: false,
  getAppPath: vi.fn(),
}));

vi.mock("electron", () => ({
  app: mockApp,
}));

// Import the security helpers after mocking.
import {
  DEV_ORIGIN,
  hasExactOrigin,
  isValidOrigin,
  isAllowedNavigation,
  resolveRepoRoot,
  resolvePythonPath,
  resolvePreloadPath,
} from "../src/main/security";

describe("Security helpers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApp.isPackaged = false;
    // In development, app.getAppPath() returns the desktop/ directory.
    mockApp.getAppPath.mockReturnValue("/fake/repo/desktop");
  });

  describe("hasExactOrigin", () => {
    it("accepts the exact dev origin", () => {
      expect(hasExactOrigin("http://localhost:5173", DEV_ORIGIN)).toBe(true);
    });

    it("accepts the exact dev origin with a path", () => {
      expect(hasExactOrigin("http://localhost:5173/src/renderer", DEV_ORIGIN)).toBe(true);
    });

    it("rejects a different port", () => {
      expect(hasExactOrigin("http://localhost:5174", DEV_ORIGIN)).toBe(false);
    });

    it("rejects a different host", () => {
      expect(hasExactOrigin("http://evil.com:5173", DEV_ORIGIN)).toBe(false);
    });

    it("rejects a URL that starts with the origin but has a different scheme", () => {
      expect(hasExactOrigin("https://localhost:5173", DEV_ORIGIN)).toBe(false);
    });

    it("rejects a URL that has the origin as a substring but different origin", () => {
      // This is the key test: startsWith would accept this, but exact origin won't.
      expect(hasExactOrigin("http://localhost:5173.evil.com", DEV_ORIGIN)).toBe(false);
    });

    it("rejects an invalid URL", () => {
      expect(hasExactOrigin("not-a-url", DEV_ORIGIN)).toBe(false);
    });
  });

  describe("isValidOrigin (development)", () => {
    it("accepts the exact dev origin", () => {
      expect(isValidOrigin("http://localhost:5173")).toBe(true);
    });

    it("rejects a different origin", () => {
      expect(isValidOrigin("http://evil.com:5173")).toBe(false);
    });

    it("rejects file:// URLs in development", () => {
      expect(isValidOrigin("file:///path/to/index.html")).toBe(false);
    });
  });

  describe("isValidOrigin (packaged)", () => {
    beforeEach(() => {
      mockApp.isPackaged = true;
    });

    it("fails closed — rejects everything", () => {
      expect(isValidOrigin("http://localhost:5173")).toBe(false);
      expect(isValidOrigin("file:///path/to/index.html")).toBe(false);
    });
  });

  describe("isAllowedNavigation", () => {
    it("allows the exact dev origin with a path", () => {
      expect(isAllowedNavigation("http://localhost:5173/src/renderer")).toBe(true);
    });

    it("blocks a different origin", () => {
      expect(isAllowedNavigation("http://evil.com")).toBe(false);
    });

    it("blocks file:// URLs in development", () => {
      expect(isAllowedNavigation("file:///etc/passwd")).toBe(false);
    });

    it("fails closed in packaged mode", () => {
      mockApp.isPackaged = true;
      expect(isAllowedNavigation("http://localhost:5173")).toBe(false);
    });
  });

  describe("resolveRepoRoot", () => {
    it("resolves to the parent of the app path in development", () => {
      const result = resolveRepoRoot();
      expect(result).toBe("/fake/repo");
    });

    it("does not return process.execPath", () => {
      const result = resolveRepoRoot();
      expect(result).not.toBe(process.execPath);
    });
  });

  describe("resolvePythonPath", () => {
    it("resolves to <repo>/src", () => {
      const result = resolvePythonPath();
      expect(result).toBe(path.join("/fake/repo", "src"));
    });
  });

  describe("resolvePreloadPath", () => {
    it("resolves to dist-electron/preload/index.js", () => {
      const result = resolvePreloadPath();
      // The path should end with preload/index.js
      expect(result).toMatch(/preload[/\\]index\.js$/);
    });

    it("does not point to main/preload/index.js", () => {
      const result = resolvePreloadPath();
      expect(result).not.toMatch(/main[/\\]preload/);
    });
  });
});
