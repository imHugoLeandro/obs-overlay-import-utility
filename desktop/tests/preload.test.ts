/**
 * Tests for the preload script's IPC transport.
 *
 * These tests verify the preload logic in isolation by mocking the
 * Electron `contextBridge` and `ipcRenderer` modules.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Define mock state that the factory will use.
// Using vi.hoisted ensures these are initialized before vi.mock runs.
const { contextBridge, ipcRenderer } = vi.hoisted(() => {
  const contextBridge = {
    exposeInMainWorld: vi.fn(),
  };
  const ipcRenderer = {
    invoke: vi.fn(),
  };
  return { contextBridge, ipcRenderer };
});

vi.mock("electron", () => ({
  contextBridge,
  ipcRenderer,
}));

// Import the preload module (this triggers contextBridge.exposeInMainWorld).
import "../src/preload/index";

describe("Preload script", () => {
  // The preload module runs at import time, so exposeInMainWorld is called
  // once during module initialization. We capture the API object here.
  const apiCall = contextBridge.exposeInMainWorld.mock.calls[0];
  const api = apiCall ? apiCall[1] : undefined;

  beforeEach(() => {
    // Only clear the IPC renderer mocks, not the contextBridge mock
    // (which was called during module initialization and we captured it above).
    ipcRenderer.invoke.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("exposes electronAPI via contextBridge", () => {
    // The preload module calls exposeInMainWorld during import.
    expect(contextBridge.exposeInMainWorld).toHaveBeenCalledWith(
      "electronAPI",
      expect.objectContaining({
        health: expect.any(Function),
        appInfo: expect.any(Function),
        chooseOverlayFolder: expect.any(Function),
        scanCollections: expect.any(Function),
        chooseCollection: expect.any(Function),
        convertCollection: expect.any(Function),
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
      "automaticImport",
      "buildExportPlan",
      "chooseAutomaticFolder",
      "chooseCollection",
      "chooseExportDestination",
      "chooseOverlayFolder",
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
      "scanCollections",
    ]);
  });

  it("does not expose raw paths or raw IPC", () => {
    expect(api).toBeDefined();
    const keys = Object.keys(api);
    // No raw filesystem, shell, or process APIs.
    expect(keys).not.toContain("readFile");
    expect(keys).not.toContain("writeFile");
    expect(keys).not.toContain("shell");
    expect(keys).not.toContain("exec");
    expect(keys).not.toContain("spawn");
    expect(keys).not.toContain("process");
    expect(keys).not.toContain("chooseFolder");
    // Only invoke is used (no send, on, once, etc.)
    expect(typeof ipcRenderer.invoke).toBe("function");
  });

  it("health invokes the fixed desktop:health channel", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      status: "ok",
      pid: 1234,
      uptime_seconds: 1.5,
      python_version: "3.13.0",
    });

    api.health();

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:health");
  });

  it("appInfo invokes the fixed desktop:app-info channel", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      name: "Test App",
      version: "1.0.0",
    });

    api.appInfo();

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:app-info");
  });

  it("chooseOverlayFolder invokes its fixed channel with no payload", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      selection_id: "sel-123",
      folder_label: "overlay",
    });

    api.chooseOverlayFolder();

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:choose-overlay-folder");
  });

  it("chooseStreamlabsOverlay invokes its fixed channel with no payload", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      selection_id: "sel-456",
      folder_label: "demo.overlay",
    });

    api.chooseStreamlabsOverlay();

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:choose-streamlabs-overlay");
  });

  it("scanCollections invokes the fixed desktop:scan-collections channel with selection_id only", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      selection_id: "sel-123",
      folder_label: "overlay",
      collections: [{ collection_id: "col-1", label: "collection.json" }],
      count: 1,
    });

    api.scanCollections("sel-123");

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:scan-collections", {
      selection_id: "sel-123",
    });
  });

  it("chooseCollection invokes the fixed desktop:choose-collection channel with selection_id and collection_id", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      selection_id: "sel-123",
      collection_label: "collection.json",
    });

    api.chooseCollection("sel-123", "col-1");

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:choose-collection", {
      selection_id: "sel-123",
      collection_id: "col-1",
    });
  });

  it("convertCollection invokes the fixed desktop:convert-collection channel with selection_id, strict, case_sensitive", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      success: true,
      changed: 1,
      unchanged: 0,
      missing: [],
      ambiguous: [],
      indexed_files: 10,
      candidate_paths: 5,
      output_filename: "collection_ImportReady.json",
    });

    api.convertCollection("sel-123", true, true);

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:convert-collection", {
      selection_id: "sel-123",
      strict: true,
      case_sensitive: true,
    });
  });

  it("importStreamlabs invokes the fixed desktop:import-streamlabs channel with selection_id only", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      success: true,
      collection_name: "Demo",
      canvas_width: 2560,
      canvas_height: 1440,
      imported_sources: 3,
      skipped_sources: [],
      profile_name: null,
      error: null,
    });

    api.importStreamlabs("sel-123");

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:import-streamlabs", {
      selection_id: "sel-123",
    });
  });

  it("automaticImport invokes the fixed desktop:automatic-import channel with selection_id, strict, case_sensitive", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      success: true,
      kind: "obs",
      collection_name: "Imported Pack",
      canvas_width: 2560,
      canvas_height: 1440,
      profile_name: "Streaming",
      error: null,
      conversion: null,
    });

    api.automaticImport("sel-123", true, true);

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:automatic-import", {
      selection_id: "sel-123",
      strict: true,
      case_sensitive: true,
    });
  });

  it("deviceRequirements invokes the fixed desktop:device-requirements channel with collection_path only", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      requirements: [{ key: "k1", name: "Camera", source_id: "av_capture_input", kind: "Camera or capture device" }],
      count: 1,
    });

    api.deviceRequirements("/path/to/collection.json");

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:device-requirements", {
      collection_path: "/path/to/collection.json",
    });
  });

  it("deviceCandidates invokes the fixed desktop:device-candidates channel with obs_scenes_directory and optional exclude_collection", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      candidates: [{ candidate_id: "dev-av-0", source_id: "av_capture_input", label: "Camera — Current", kind: "Camera or capture device" }],
      count: 1,
    });

    api.deviceCandidates("/obs/scenes", "/obs/scenes/Imported.json");

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:device-candidates", {
      obs_scenes_directory: "/obs/scenes",
      exclude_collection: "/obs/scenes/Imported.json",
    });
  });

  it("applyDeviceChoices invokes the fixed desktop:apply-device-choices channel with collection_path and choices", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      success: true,
      error: null,
    });

    api.applyDeviceChoices("/path/to/collection.json", { k1: "disable" });

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:apply-device-choices", {
      collection_path: "/path/to/collection.json",
      choices: { k1: "disable" },
    });
  });

  it("obsRunning invokes the fixed desktop:obs-running channel with no payload", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({ running: true });

    api.obsRunning();

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:obs-running");
  });

  it("activateCollection invokes the fixed desktop:activate-collection channel with collection_name and optional password", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      success: true,
      error: null,
    });

    api.activateCollection("My Collection", "secret123");

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:activate-collection", {
      collection_name: "My Collection",
      password: "secret123",
    });
  });

  it("listExportCollections invokes the fixed desktop:list-export-collections channel with obs_scenes_directory only", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      collections: [{ label: "Current", path: "/obs/scenes/Current.json" }],
      count: 1,
    });

    api.listExportCollections("/obs/scenes");

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:list-export-collections", {
      obs_scenes_directory: "/obs/scenes",
    });
  });

  it("chooseExportDestination invokes the fixed desktop:choose-export-destination channel with no payload", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      destination_path: "/export",
      destination_label: "export",
    });

    api.chooseExportDestination();

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:choose-export-destination");
  });

  it("buildExportPlan invokes the fixed desktop:build-export-plan channel with collection_path, destination, compressed", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      plan_id: "plan-123",
      collection_label: "Current",
      collection_stem: "Current",
      compressed: false,
      source_references: 5,
      total_bytes: 1024,
      scene_count: 3,
      source_count: 5,
      browser_files: 0,
      canvas_width: 2560,
      canvas_height: 1440,
      missing_references: [],
      dependency_report: {
        fonts: [],
        devices: [],
        remote_resources: [],
        plugin_source_ids: [],
        plugin_filter_ids: [],
      },
      items: [],
    });

    api.buildExportPlan("/path/to/collection.json", "/export", false);

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:build-export-plan", {
      collection_path: "/path/to/collection.json",
      destination: "/export",
      compressed: false,
    });
  });

  it("exportInventory invokes the fixed desktop:export-inventory channel with plan_id only", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      plan_id: "plan-123",
      collection_label: "Current",
      collection_stem: "Current",
      compressed: false,
      source_references: 5,
      total_bytes: 1024,
      scene_count: 3,
      source_count: 5,
      browser_files: 0,
      canvas_width: 2560,
      canvas_height: 1440,
      missing_references: [],
      items: [],
    });

    api.exportInventory("plan-123");

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:export-inventory", {
      plan_id: "plan-123",
    });
  });

  it("confirmExport invokes the fixed desktop:confirm-export channel with plan_id only", () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockResolvedValue({
      success: true,
      already_executed: false,
      copied_files: 5,
      uncompressed_bytes: 1024,
      source_references: 5,
      skipped_references: [],
      verification: { ok: true, errors: [] },
      output_label: "Current-Portable",
      error: null,
    });

    api.confirmExport("plan-123");

    expect(ipcRenderer.invoke).toHaveBeenCalledTimes(1);
    expect(ipcRenderer.invoke).toHaveBeenCalledWith("desktop:confirm-export", {
      plan_id: "plan-123",
    });
  });

  it("rejects error responses from the backend", async () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockRejectedValue(new Error("Backend unavailable"));

    await expect(api.health()).rejects.toThrow("Backend unavailable");
  });

  it("does not expose chooseFolder (renamed to chooseOverlayFolder)", () => {
    expect(api).toBeDefined();
    expect(api.chooseFolder).toBeUndefined();
    expect(api.chooseOverlayFolder).toBeDefined();
  });

  it("does not accept a renderer-provided folder path", () => {
    expect(api).toBeDefined();
    // chooseOverlayFolder takes no parameters.
    expect(api.chooseOverlayFolder.length).toBe(0);
  });
});
