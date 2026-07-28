/**
 * Tests for the preload script's IPC transport.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const { contextBridge, ipcRenderer } = vi.hoisted(() => {
  const contextBridge = { exposeInMainWorld: vi.fn() };
  const ipcRenderer = { invoke: vi.fn() };
  return { contextBridge, ipcRenderer };
});

vi.mock("electron", () => ({ contextBridge, ipcRenderer }));

import "../src/preload/index";

describe("Preload script", () => {
  const apiCall = contextBridge.exposeInMainWorld.mock.calls[0];
  const api = apiCall ? apiCall[1] : undefined;

  beforeEach(() => {
    ipcRenderer.invoke.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("exposes electronAPI via contextBridge", () => {
    expect(contextBridge.exposeInMainWorld).toHaveBeenCalledWith(
      "electronAPI",
      expect.objectContaining({
        health: expect.any(Function),
        appInfo: expect.any(Function),
      })
    );
  });

  it("exposes exactly the finite API surface", () => {
    expect(api).toBeDefined();
    const keys = Object.keys(api).sort();
    expect(keys).toEqual([
      "activateCollection",
      "appInfo",
      "applyDeviceChoices",
      "applyResize",
      "automaticImport",
      "buildExportPlan",
      "chooseAutomaticFolder",
      "chooseCollection",
      "chooseExportDestination",
      "chooseOverlayFolder",
      "chooseResizeCollection",
      "chooseStreamlabsOverlay",
      "confirmExport",
      "convertCollection",
      "deviceCandidates",
      "deviceRequirements",
      "exportInventory",
      "health",
      "importStreamlabs",
      "listExportCollections",
      "obsRunning",
      "previewResize",
      "resizeSceneChoices",
      "resizeSourceChoices",
      "scanCollections",
      "scanResizeCollections",
      "undoResize",
    ]);
  });

  it("does not expose raw paths or raw IPC", () => {
    expect(api).toBeDefined();
    const keys = Object.keys(api);
    expect(keys).not.toContain("readFile");
    expect(keys).not.toContain("writeFile");
    expect(keys).not.toContain("shell");
    expect(keys).not.toContain("exec");
    expect(keys).not.toContain("spawn");
    expect(keys).not.toContain("process");
    expect(keys).not.toContain("chooseFolder");
    expect(typeof ipcRenderer.invoke).toBe("function");
  });

  it("health invokes desktop:health", () => {
    ipcRenderer.invoke.mockResolvedValue({ status: "ok", pid: 1234, uptime_seconds: 1.5, python_version: "3.13.0" });
    api.health();
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:health");
  });

  it("chooseOverlayFolder takes no parameters", () => {
    expect(api.chooseOverlayFolder.length).toBe(0);
  });

  it("chooseStreamlabsOverlay takes no parameters", () => {
    expect(api.chooseStreamlabsOverlay.length).toBe(0);
  });

  it("chooseAutomaticFolder takes no parameters", () => {
    expect(api.chooseAutomaticFolder.length).toBe(0);
  });

  it("deviceRequirements takes only installationId (no raw path)", () => {
    ipcRenderer.invoke.mockResolvedValue({ requirements: [], count: 0 });
    api.deviceRequirements("inst-123");
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:device-requirements", {
      installation_id: "inst-123",
    });
  });

  it("deviceCandidates takes only installationId (no raw path)", () => {
    ipcRenderer.invoke.mockResolvedValue({ candidates: [], count: 0 });
    api.deviceCandidates("inst-123");
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:device-candidates", {
      installation_id: "inst-123",
    });
  });

  it("applyDeviceChoices takes installationId (no raw path)", () => {
    ipcRenderer.invoke.mockResolvedValue({ success: true, error: null });
    api.applyDeviceChoices("inst-123", { k1: "disable" });
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:apply-device-choices", {
      installation_id: "inst-123",
      choices: { k1: "disable" },
    });
  });

  it("activateCollection takes installationId (no raw collection name)", () => {
    ipcRenderer.invoke.mockResolvedValue({ success: true, error: null });
    api.activateCollection("inst-123", "secret");
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:activate-collection", {
      installation_id: "inst-123",
      password: "secret",
    });
  });

  it("listExportCollections takes no renderer arguments", () => {
    ipcRenderer.invoke.mockResolvedValue({ collections: [], count: 0 });
    api.listExportCollections();
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:list-export-collections");
  });

  it("chooseExportDestination returns opaque destination_id", () => {
    ipcRenderer.invoke.mockResolvedValue({ destination_id: "dest-123", destination_label: "exports" });
    api.chooseExportDestination();
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:choose-export-destination");
  });

  it("buildExportPlan takes opaque collection_id and destination_id", () => {
    ipcRenderer.invoke.mockResolvedValue({ plan_id: "plan-123", collection_label: "Current", collection_stem: "Current", compressed: false, source_references: 0, total_bytes: 0, scene_count: 0, source_count: 0, browser_files: 0, canvas_width: null, canvas_height: null, missing_references: [], dependency_report: { fonts: [], devices: [], remote_resources: [], plugin_source_ids: [], plugin_filter_ids: [] }, items: [] });
    api.buildExportPlan("col-123", "dest-123", false);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:build-export-plan", {
      collection_id: "col-123",
      destination_id: "dest-123",
      compressed: false,
    });
  });

  it("undoResize takes only opaque IDs (no raw backup path)", () => {
    ipcRenderer.invoke.mockResolvedValue({ success: true, error: null });
    api.undoResize("sel-123", "undo-abc");
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:undo-resize", {
      selection_id: "sel-123",
      undo_id: "undo-abc",
    });
  });

  it("undoResize does not send backup_path", () => {
    ipcRenderer.invoke.mockResolvedValue({ success: true, error: null });
    api.undoResize("sel-123", "undo-abc");
    const callArgs = ipcRenderer.invoke.mock.calls[0];
    expect(callArgs[1]).not.toHaveProperty("backup_path");
    expect(callArgs[1]).toHaveProperty("undo_id");
  });

  it("resizeSceneChoices takes only selectionId", () => {
    ipcRenderer.invoke.mockResolvedValue({ scenes: ["Scene 1", "Scene 2"], count: 2 });
    api.resizeSceneChoices("sel-123");
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:resize-scene-choices", {
      selection_id: "sel-123",
    });
  });

  it("does not expose applyLiveResize or undoLiveResize", () => {
    expect(api.applyLiveResize).toBeUndefined();
    expect(api.undoLiveResize).toBeUndefined();
  });

  it("does not expose chooseFolder (renamed to chooseOverlayFolder)", () => {
    expect(api.chooseFolder).toBeUndefined();
    expect(api.chooseOverlayFolder).toBeDefined();
  });
});
