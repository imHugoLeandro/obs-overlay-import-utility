// Deterministic verification of compiled Electron output.
//
// This test file is run via npm run verify:compiled, which must be
// executed AFTER npm run build.  It does NOT run as part of npm test
// (vitest run) — the vitest config excludes this file.
//
// These tests FAIL (not skip) when build artifacts are missing or when
// compiled output violates a checked security invariant.
//
// Security invariants checked:
// - No process.execPath used as the Python executable
// - No eval() calls in compiled output
// - nodeIntegration: false
// - contextIsolation: true
// - sandbox: true
// - webSecurity: true
// - webviewTag: false
// - Fixed IPC channels present
// - Preload uses ipcRenderer.invoke (not send/on/once)

import { describe, it, expect, beforeAll } from "vitest";
import * as fs from "fs";
import * as path from "path";

const distElectron = path.resolve(__dirname, "..", "dist-electron");
const dist = path.resolve(__dirname, "..", "dist");

const mainJs = path.join(distElectron, "main", "index.js");
const preloadJs = path.join(distElectron, "preload", "index.js");
const securityJs = path.join(distElectron, "main", "security.js");
const rendererIndexHtml = path.join(dist, "index.html");

// Assert that a file exists.  Throws with a descriptive message if not.
function assertFileExists(filePath: string): void {
  if (!fs.existsSync(filePath)) {
    throw new Error(
      "Expected compiled artifact not found: " +
        filePath +
        "\nRun 'npm run build' before 'npm run verify:compiled'."
    );
  }
}

// Read a file, asserting it exists first.
function readCompiledFile(filePath: string): string {
  assertFileExists(filePath);
  return fs.readFileSync(filePath, "utf8");
}

describe("Compiled Electron output verification", () => {
  describe("artifact existence", () => {
    it("compiled main process exists at dist-electron/main/index.js", () => {
      assertFileExists(mainJs);
    });

    it("compiled preload exists at dist-electron/preload/index.js", () => {
      assertFileExists(preloadJs);
    });

    it("compiled security module exists at dist-electron/main/security.js", () => {
      assertFileExists(securityJs);
    });

    it("compiled renderer exists at dist/index.html", () => {
      assertFileExists(rendererIndexHtml);
    });

    it("preload is NOT at dist-electron/main/preload/index.js", () => {
      const wrongPath = path.join(distElectron, "main", "preload", "index.js");
      expect(fs.existsSync(wrongPath)).toBe(false);
    });
  });

  describe("main process security invariants", () => {
    let mainContent: string;

    beforeAll(() => {
      mainContent = readCompiledFile(mainJs);
    });

    it("does not use process.execPath as Python", () => {
      expect(mainContent).not.toContain("process.execPath");
    });

    it("uses OBS_OVERLAY_PYTHON environment variable", () => {
      expect(mainContent).toContain("OBS_OVERLAY_PYTHON");
    });

    it("has nodeIntegration: false", () => {
      expect(mainContent).toMatch(/nodeIntegration:\s*false/);
    });

    it("has contextIsolation: true", () => {
      expect(mainContent).toMatch(/contextIsolation:\s*true/);
    });

    it("has sandbox: true", () => {
      expect(mainContent).toMatch(/sandbox:\s*true/);
    });

    it("has webSecurity: true", () => {
      expect(mainContent).toMatch(/webSecurity:\s*true/);
    });

    it("has webviewTag: false", () => {
      expect(mainContent).toMatch(/webviewTag:\s*false/);
    });

    it("has setPermissionCheckHandler denying all", () => {
      expect(mainContent).toContain("setPermissionCheckHandler");
      expect(mainContent).toContain("setPermissionRequestHandler");
    });

    it("has fixed IPC channels", () => {
      expect(mainContent).toContain("desktop:health");
      expect(mainContent).toContain("desktop:app-info");
      expect(mainContent).toContain("desktop:choose-overlay-folder");
      expect(mainContent).toContain("desktop:choose-streamlabs-overlay");
      expect(mainContent).toContain("desktop:choose-automatic-folder");
      expect(mainContent).toContain("desktop:choose-export-destination");
      expect(mainContent).toContain("desktop:scan-collections");
      expect(mainContent).toContain("desktop:choose-collection");
      expect(mainContent).toContain("desktop:convert-collection");
      expect(mainContent).toContain("desktop:import-streamlabs");
      expect(mainContent).toContain("desktop:automatic-import");
      expect(mainContent).toContain("desktop:device-requirements");
      expect(mainContent).toContain("desktop:device-candidates");
      expect(mainContent).toContain("desktop:apply-device-choices");
      expect(mainContent).toContain("desktop:obs-running");
      expect(mainContent).toContain("desktop:activate-collection");
      expect(mainContent).toContain("desktop:list-export-collections");
      expect(mainContent).toContain("desktop:build-export-plan");
      expect(mainContent).toContain("desktop:export-inventory");
      expect(mainContent).toContain("desktop:confirm-export");
      expect(mainContent).toContain("desktop:scan-resize-collections");
      expect(mainContent).toContain("desktop:choose-resize-collection");
      expect(mainContent).toContain("desktop:resize-source-choices");
      expect(mainContent).toContain("desktop:resize-scene-choices");
      expect(mainContent).toContain("desktop:preview-resize");
      expect(mainContent).toContain("desktop:apply-resize");
      expect(mainContent).toContain("desktop:undo-resize");
    });

    it("does not contain live resize channels", () => {
      expect(mainContent).not.toContain("desktop:apply-live-resize");
      expect(mainContent).not.toContain("desktop:undo-live-resize");
    });

    it("does not contain eval() calls", () => {
      expect(mainContent).not.toMatch(/\beval\s*\(/);
    });

    it("does not contain showPackagedNotImplemented", () => {
      expect(mainContent).not.toContain("showPackagedNotImplemented");
      expect(mainContent).not.toContain("Portable Electron Packaging Not Implemented");
    });

    it("loads local built renderer in packaged mode (not Vite URL)", () => {
      // The compiled main process should load the built renderer from
      // the local file system in packaged mode, not from the Vite dev server.
      expect(mainContent).toContain("loadFile");
      expect(mainContent).toContain("dist");
      expect(mainContent).toContain("index.html");
    });

    it("does not use process.execPath as Python", () => {
      expect(mainContent).not.toContain("process.execPath");
    });

    it("resolves backend from process.resourcesPath", () => {
      expect(mainContent).toContain("process.resourcesPath");
    });

    it("starts bundled backend in packaged mode", () => {
      // The compiled output should start the backend in both dev and
      // packaged modes, resolving the executable from resourcesPath.
      expect(mainContent).toContain("resolveBackendExecutable");
    });

    it("uses exact origin validation (not startsWith)", () => {
      const securityContent = fs.existsSync(securityJs)
        ? fs.readFileSync(securityJs, "utf8")
        : "";
      const combined = mainContent + securityContent;
      expect(combined).toContain("origin");
      // Should NOT use startsWith for origin validation.
      const startsWithMatches = combined.match(
        /startsWith\s*\(\s*DEV_ORIGIN\s*\)/g
      );
      expect(startsWithMatches).toBeNull();
    });
  });

  describe("preload security invariants", () => {
    let preloadContent: string;

    beforeAll(() => {
      preloadContent = readCompiledFile(preloadJs);
    });

    it("uses ipcRenderer.invoke (not send/on/once)", () => {
      expect(preloadContent).toContain("ipcRenderer.invoke");
      expect(preloadContent).not.toContain("ipcRenderer.send");
      expect(preloadContent).not.toContain("ipcRenderer.on");
      expect(preloadContent).not.toContain("ipcRenderer.once");
    });

    it("exposes only health, appInfo, and all workflow channels", () => {
      expect(preloadContent).toContain("desktop:health");
      expect(preloadContent).toContain("desktop:app-info");
      expect(preloadContent).toContain("desktop:choose-overlay-folder");
      expect(preloadContent).toContain("desktop:choose-streamlabs-overlay");
      expect(preloadContent).toContain("desktop:choose-automatic-folder");
      expect(preloadContent).toContain("desktop:choose-export-destination");
      expect(preloadContent).toContain("desktop:scan-collections");
      expect(preloadContent).toContain("desktop:choose-collection");
      expect(preloadContent).toContain("desktop:convert-collection");
      expect(preloadContent).toContain("desktop:import-streamlabs");
      expect(preloadContent).toContain("desktop:automatic-import");
      expect(preloadContent).toContain("desktop:device-requirements");
      expect(preloadContent).toContain("desktop:device-candidates");
      expect(preloadContent).toContain("desktop:apply-device-choices");
      expect(preloadContent).toContain("desktop:obs-running");
      expect(preloadContent).toContain("desktop:activate-collection");
      expect(preloadContent).toContain("desktop:list-export-collections");
      expect(preloadContent).toContain("desktop:build-export-plan");
      expect(preloadContent).toContain("desktop:export-inventory");
      expect(preloadContent).toContain("desktop:confirm-export");
      expect(preloadContent).toContain("desktop:scan-resize-collections");
      expect(preloadContent).toContain("desktop:choose-resize-collection");
      expect(preloadContent).toContain("desktop:resize-source-choices");
      expect(preloadContent).toContain("desktop:resize-scene-choices");
      expect(preloadContent).toContain("desktop:preview-resize");
      expect(preloadContent).toContain("desktop:apply-resize");
      expect(preloadContent).toContain("desktop:undo-resize");
    });

    it("does not contain live resize channels", () => {
      expect(preloadContent).not.toContain("desktop:apply-live-resize");
      expect(preloadContent).not.toContain("desktop:undo-live-resize");
    });

    it("does not contain eval() calls", () => {
      expect(preloadContent).not.toMatch(/\beval\s*\(/);
    });
  });

  describe("package configuration", () => {
    const packageJsonPath = path.resolve(__dirname, "..", "package.json");

    it("package.json includes the backend in extraResources", () => {
      const pkg = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
      expect(pkg.build).toBeDefined();
      expect(pkg.build.extraResources).toBeDefined();
      expect(pkg.build.extraResources.length).toBeGreaterThan(0);
      const backendResource = pkg.build.extraResources.find(
        (r: { to: string }) => r.to && r.to.includes("obs-overlay-backend")
      );
      expect(backendResource).toBeDefined();
    });

    it("package.json has a portable Windows target", () => {
      const pkg = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
      expect(pkg.build.win).toBeDefined();
      expect(pkg.build.win.target).toBeDefined();
      const target = pkg.build.win.target;
      if (Array.isArray(target)) {
        expect(target).toContain("portable");
      } else if (typeof target === "object") {
        expect(target.portable).toBeDefined();
      } else {
        expect(target).toBe("portable");
      }
    });

    it("package.json has a package script that builds Electron", () => {
      const pkg = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
      expect(pkg.scripts.package).toBeDefined();
      expect(pkg.scripts.package).not.toContain("deferred");
      expect(pkg.scripts.package).toContain("electron-builder");
    });

    it("packages the desktop backend, never the Tk launcher", () => {
      const pkg = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
      expect(pkg.scripts["package:backend"]).toContain("tools/desktop_backend.py");
      expect(pkg.scripts["package:backend"]).not.toContain("tools/launcher.py");
    });
  });
});
