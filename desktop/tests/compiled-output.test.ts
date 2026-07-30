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
import { IPC_CHANNELS } from "../src/shared/ipcChannels";

const distElectron = path.resolve(__dirname, "..", "dist-electron");
const dist = path.resolve(__dirname, "..", "dist");

const mainJs = path.join(distElectron, "main", "index.js");
const preloadJs = path.join(distElectron, "preload", "index.js");
const securityJs = path.join(distElectron, "main", "security.js");
const sharedChannelsJs = path.join(distElectron, "shared", "ipcChannels.js");
const rendererIndexHtml = path.join(dist, "index.html");
const mainSource = path.resolve(__dirname, "..", "src", "main", "index.ts");
const preloadSource = path.resolve(__dirname, "..", "src", "preload", "index.ts");

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

    it("compiled shared IPC contract exists", () => {
      assertFileExists(sharedChannelsJs);
    });

    it("compiled renderer exists at dist/index.html", () => {
      assertFileExists(rendererIndexHtml);
    });

    it("preload is NOT at dist-electron/main/preload/index.js", () => {
      const wrongPath = path.join(distElectron, "main", "preload", "index.js");
      expect(fs.existsSync(wrongPath)).toBe(false);
    });
  });

  describe("shared IPC contract", () => {
    it("has a pure complete fixed shared contract", () => {
      const source = fs.readFileSync(
        path.resolve(__dirname, "..", "src", "shared", "ipcChannels.ts"),
        "utf8"
      );
      const channelValues = Object.values(IPC_CHANNELS);

      expect(channelValues).toHaveLength(new Set(channelValues).size);
      expect(channelValues.every((channel) => /^desktop:[a-z-]+$/.test(channel))).toBe(true);
      expect(source).not.toMatch(/^\s*import\s+.*from\s+["'](?:electron|node:)/m);
      expect(source).not.toMatch(/\b(require|process|__dirname)\b|\b(?:path|fs|app)\./);
      expect(source).not.toMatch(/\[.*\+.*\]|\.concat\(/);
      expect(Object.keys(IPC_CHANNELS)).toHaveLength(27);
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

    it("uses the canonical fixed IPC channel registry", () => {
      const channelValues = Object.values(IPC_CHANNELS);
      const sharedChannelsContent = readCompiledFile(sharedChannelsJs);
      const source = fs.readFileSync(mainSource, "utf8");

      expect(channelValues).toHaveLength(new Set(channelValues).size);
      expect(channelValues.every((channel) => /^desktop:[a-z-]+$/.test(channel))).toBe(true);
      for (const channel of channelValues) {
        expect(sharedChannelsContent).toContain(channel);
      }
      expect(mainContent).toContain("shared/ipcChannels");
      expect(source).toContain("IPC_CHANNELS");
      expect(source).toMatch(/ipcMain\.handle\([A-Z_]+_CHANNEL/);
      expect(source).not.toMatch(/ipcMain\.handle\(\s*["'`]/);
      expect(source).not.toMatch(/ipcMain\.handle\([^,]*\bcommand\b/i);
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
      expect(mainContent).toMatch(
        /if \(electron_1\.app\.isPackaged\)[\s\S]*?loadFile\(\(0, security_1\.resolvePackagedRendererPath\)\(\)\)[\s\S]*?else[\s\S]*?loadURL\(security_1\.DEV_ORIGIN\)/
      );
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

    it("bundles the fixed preload API without local runtime imports", () => {
      const source = fs.readFileSync(preloadSource, "utf8");

      expect(source).toContain("../shared/ipcChannels");
      expect(preloadContent).not.toMatch(/require\(\s*["']\.\.?[\\/]/);
      expect(preloadContent).not.toContain("main/contracts/channels");
      expect(preloadContent).not.toContain("shared/ipcChannels");
      expect(preloadContent).toMatch(/require\(\s*["']electron["']\s*\)/);
      for (const [key, channel] of Object.entries(IPC_CHANNELS)) {
        expect(source).toContain(`IPC_CHANNELS.${key}`);
        expect(preloadContent).toContain(channel);
      }
      expect(source).not.toMatch(/ipcRenderer\.invoke\(\s*["'`]/);
      expect(source).not.toMatch(/ipcRenderer\.invoke\([^)]*\bchannel\b/i);
      expect(preloadContent).toContain("contextBridge.exposeInMainWorld");
      expect(preloadContent).not.toMatch(/nodeIntegration|sandbox\s*:\s*false/);
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

    it("keeps Electron as a pinned build dependency", () => {
      const pkg = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
      expect(pkg.dependencies?.electron).toBeUndefined();
      expect(pkg.devDependencies.electron).toBe("43.2.0");
    });

    it("keeps packaging as an already-built artifact pipeline", () => {
      const pkg = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
      expect(pkg.scripts.package).toBe("electron-builder --win --publish=never");
      expect(pkg.scripts["package:all"]).toContain("npm run build");
      expect(pkg.scripts["package:all"]).toContain("npm run verify:compiled");
      expect(pkg.scripts["package:all"]).toContain("npm run package:backend");
    });

    it("keeps Electron packaging separate from the Tk fallback scripts and workflow", () => {
      const repoRoot = path.resolve(__dirname, "..", "..");
      const readRootFile = (...segments: string[]) =>
        fs.readFileSync(path.join(repoRoot, ...segments), "utf8");
      const electronScript = readRootFile("scripts", "build_portable_electron.ps1");
      const tkScript = readRootFile("scripts", "build_portable_tk.ps1");
      const compatibilityScript = readRootFile("scripts", "build_portable.ps1");
      const workflow = readRootFile(".github", "workflows", "build-windows.yml");
      const desktopReadme = readRootFile("desktop", "README.md");

      expect(electronScript).toContain(".venv-build-electron");
      expect(electronScript).toContain("npm run package:all");
      expect(electronScript).not.toContain("tools\\launcher.py");
      expect(electronScript).not.toContain("ui.py");
      expect(workflow).toContain("npm run package:backend");
      expect(workflow).toContain("npm run package");
      expect(workflow).not.toContain("tools/launcher.py");
      expect(workflow).not.toContain("ui.py");
      expect(tkScript).toContain("legacy Tk fallback");
      expect(tkScript).toContain("tools\\launcher.py");
      expect(compatibilityScript).toContain("[switch] $LegacyTk");
      expect(compatibilityScript).toContain("build_portable_electron.ps1");
      expect(compatibilityScript).toContain("build_portable_tk.ps1");
      expect(compatibilityScript).not.toContain("PyInstaller");
      expect(desktopReadme).toContain("build_portable_electron.ps1");
      expect(desktopReadme).not.toMatch(/deferred to Stage|Tk remains the shipping\/default/i);
    });
  });
});
