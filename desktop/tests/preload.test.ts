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
      "appInfo",
      "chooseCollection",
      "chooseOverlayFolder",
      "convertCollection",
      "health",
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
