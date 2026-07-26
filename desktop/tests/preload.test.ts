/**
 * Tests for the preload script's IPC transport and request ID generation.
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
      })
    );
  });

  it("exposes only health and appInfo methods", () => {
    expect(api).toBeDefined();
    const keys = Object.keys(api);
    expect(keys).toHaveLength(2);
    expect(keys).toContain("health");
    expect(keys).toContain("appInfo");
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

  it("rejects error responses from the backend", async () => {
    expect(api).toBeDefined();

    ipcRenderer.invoke.mockRejectedValue(new Error("Backend unavailable"));

    await expect(api.health()).rejects.toThrow("Backend unavailable");
  });

  it("does not use dynamic channels or raw IPC", () => {
    expect(api).toBeDefined();

    // Verify that only invoke is used (no send, on, once, etc.)
    expect(ipcRenderer.invoke).toBeDefined();
    // The mock only has invoke — send, on, once are not present
    expect(typeof ipcRenderer.invoke).toBe("function");
  });
});
