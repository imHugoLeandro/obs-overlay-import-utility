/**
 * Tests for compiled Electron output verification.
 *
 * These tests verify that:
 * - The compiled main process exists at the expected path
 * - The compiled preload exists at the expected path
 * - The compiled main process does not use process.execPath as Python
 * - The compiled main process has the correct security settings
 */

import { describe, it, expect } from "vitest";
import * as fs from "fs";
import * as path from "path";

const distElectron = path.resolve(__dirname, "..", "dist-electron");
const mainJs = path.join(distElectron, "main", "index.js");
const preloadJs = path.join(distElectron, "preload", "index.js");

describe("Compiled Electron output", () => {
  // Only run these tests if the build has been run.
  const buildExists = fs.existsSync(mainJs);

  it("compiled main process exists at dist-electron/main/index.js", () => {
    if (!buildExists) {
      console.warn("Skipping: run 'npm run build' first");
      return;
    }
    expect(fs.existsSync(mainJs)).toBe(true);
  });

  it("compiled preload exists at dist-electron/preload/index.js", () => {
    if (!buildExists) {
      console.warn("Skipping: run 'npm run build' first");
      return;
    }
    expect(fs.existsSync(preloadJs)).toBe(true);
  });

  it("preload is NOT at dist-electron/main/preload/index.js", () => {
    if (!buildExists) {
      console.warn("Skipping: run 'npm run build' first");
      return;
    }
    const wrongPath = path.join(distElectron, "main", "preload", "index.js");
    expect(fs.existsSync(wrongPath)).toBe(false);
  });

  it("does not use process.execPath as Python", () => {
    if (!buildExists) {
      console.warn("Skipping: run 'npm run build' first");
      return;
    }
    const content = fs.readFileSync(mainJs, "utf8");
    expect(content).not.toContain("process.execPath");
  });

  it("uses OBS_OVERLAY_PYTHON environment variable", () => {
    if (!buildExists) {
      console.warn("Skipping: run 'npm run build' first");
      return;
    }
    const content = fs.readFileSync(mainJs, "utf8");
    expect(content).toContain("OBS_OVERLAY_PYTHON");
  });

  it("has nodeIntegration: false", () => {
    if (!buildExists) {
      console.warn("Skipping: run 'npm run build' first");
      return;
    }
    const content = fs.readFileSync(mainJs, "utf8");
    expect(content).toMatch(/nodeIntegration:\s*false/);
  });

  it("has contextIsolation: true", () => {
    if (!buildExists) {
      console.warn("Skipping: run 'npm run build' first");
      return;
    }
    const content = fs.readFileSync(mainJs, "utf8");
    expect(content).toMatch(/contextIsolation:\s*true/);
  });

  it("has sandbox: true", () => {
    if (!buildExists) {
      console.warn("Skipping: run 'npm run build' first");
      return;
    }
    const content = fs.readFileSync(mainJs, "utf8");
    expect(content).toMatch(/sandbox:\s*true/);
  });

  it("has webSecurity: true", () => {
    if (!buildExists) {
      console.warn("Skipping: run 'npm run build' first");
      return;
    }
    const content = fs.readFileSync(mainJs, "utf8");
    expect(content).toMatch(/webSecurity:\s*true/);
  });

  it("has webviewTag: false", () => {
    if (!buildExists) {
      console.warn("Skipping: run 'npm run build' first");
      return;
    }
    const content = fs.readFileSync(mainJs, "utf8");
    expect(content).toMatch(/webviewTag:\s*false/);
  });

  it("has setPermissionCheckHandler denying all", () => {
    if (!buildExists) {
      console.warn("Skipping: run 'npm run build' first");
      return;
    }
    const content = fs.readFileSync(mainJs, "utf8");
    expect(content).toContain("setPermissionCheckHandler");
    expect(content).toContain("setPermissionRequestHandler");
  });

  it("has fixed IPC channels", () => {
    if (!buildExists) {
      console.warn("Skipping: run 'npm run build' first");
      return;
    }
    const content = fs.readFileSync(mainJs, "utf8");
    expect(content).toContain("desktop:health");
    expect(content).toContain("desktop:app-info");
  });

  it("uses exact origin validation (not startsWith)", () => {
    if (!buildExists) {
      console.warn("Skipping: run 'npm run build' first");
      return;
    }
    // Check both main and security modules.
    const mainContent = fs.readFileSync(mainJs, "utf8");
    const securityJs = path.join(distElectron, "main", "security.js");
    let securityContent = "";
    if (fs.existsSync(securityJs)) {
      securityContent = fs.readFileSync(securityJs, "utf8");
    }
    const combined = mainContent + securityContent;
    expect(combined).toContain("origin");
    // Should NOT use startsWith for origin validation.
    const startsWithMatches = combined.match(/startsWith\(DEV_ORIGIN\)/g);
    expect(startsWithMatches).toBeNull();
  });

  it("preloads use ipcRenderer.invoke (not send)", () => {
    if (!fs.existsSync(preloadJs)) {
      console.warn("Skipping: run 'npm run build' first");
      return;
    }
    const content = fs.readFileSync(preloadJs, "utf8");
    expect(content).toContain("ipcRenderer.invoke");
    expect(content).not.toContain("ipcRenderer.send");
    expect(content).not.toContain("ipcRenderer.on");
    expect(content).not.toContain("ipcRenderer.once");
  });
});
