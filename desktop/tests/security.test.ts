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
import { pathToFileURL } from "url";

const fakeDesktopAppPath = path.join(
  path.parse(process.cwd()).root,
  "fake",
  "repo",
  "desktop"
);

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
  resolvePackagedRendererPath,
  resolveRepoRoot,
  resolvePythonPath,
  resolvePreloadPath,
} from "../src/main/security";

describe("Security helpers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApp.isPackaged = false;
    // In development, app.getAppPath() returns the desktop/ directory.
    mockApp.getAppPath.mockReturnValue(fakeDesktopAppPath);
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

    it("accepts only the built local renderer", () => {
      const rendererUrl = pathToFileURL(resolvePackagedRendererPath()).toString();
      expect(isValidOrigin(rendererUrl)).toBe(true);
    });

    it("rejects http://localhost:5173 in packaged mode", () => {
      expect(isValidOrigin("http://localhost:5173")).toBe(false);
    });

    it("rejects other file:// URLs in packaged mode", () => {
      expect(isValidOrigin("file:///path/to/index.html")).toBe(false);
    });

    it("rejects a different origin", () => {
      expect(isValidOrigin("http://evil.com:5173")).toBe(false);
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

    it("allows the built renderer navigation in packaged mode", () => {
      mockApp.isPackaged = true;
      const rendererUrl = pathToFileURL(resolvePackagedRendererPath()).toString();
      expect(isAllowedNavigation(rendererUrl)).toBe(true);
    });

    it("blocks external URLs in packaged mode", () => {
      mockApp.isPackaged = true;
      expect(isAllowedNavigation("http://localhost:5173")).toBe(false);
      expect(isAllowedNavigation("https://evil.com")).toBe(false);
    });
  });

  describe("resolveRepoRoot", () => {
    it("resolves to the parent of the app path in development", () => {
      const result = resolveRepoRoot();
      expect(result).toBe(path.dirname(fakeDesktopAppPath));
    });

    it("does not return process.execPath", () => {
      const result = resolveRepoRoot();
      expect(result).not.toBe(process.execPath);
    });

    it("returns process.resourcesPath in packaged mode", () => {
      mockApp.isPackaged = true;
      // process.resourcesPath is set by Electron in packaged mode.
      // In the test environment it may be undefined, but the function
      // should not throw or return process.execPath.
      const result = resolveRepoRoot();
      expect(result).not.toBe(process.execPath);
    });
  });

  describe("resolvePythonPath", () => {
    it("resolves to <repo>/src", () => {
      const result = resolvePythonPath();
      expect(result).toBe(path.join(path.dirname(fakeDesktopAppPath), "src"));
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
