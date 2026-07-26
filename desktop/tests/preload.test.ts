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
    once: vi.fn(),
    send: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
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
    ipcRenderer.once.mockClear();
    ipcRenderer.send.mockClear();
    ipcRenderer.on.mockClear();
    ipcRenderer.off.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("exposes electronAPI via contextBridge", () => {
    // The preload module calls exposeInMainWorld during import.
    // We check the mock directly (not after clearAllMocks).
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

  it("health sends a request with the health command", () => {
    expect(api).toBeDefined();

    // Mock the ipcRenderer.once to simulate a response.
    ipcRenderer.once.mockImplementation(
      (_channel: string, cb: (event: unknown, response: unknown) => void) => {
        cb({}, { request_id: "test", type: "result", data: { status: "ok" } });
      }
    );

    api.health();

    expect(ipcRenderer.send).toHaveBeenCalledTimes(1);
    const [channel, payload] = ipcRenderer.send.mock.calls[0];
    expect(channel).toBe("desktop-backend-request");
    expect(payload.command).toBe("health");
    expect(typeof payload.request_id).toBe("string");
    expect(payload.request_id).toMatch(/^req-\d+-\d+$/);
  });

  it("appInfo sends a request with the app_info command", () => {
    expect(api).toBeDefined();

    ipcRenderer.once.mockImplementation(
      (_channel: string, cb: (event: unknown, response: unknown) => void) => {
        cb(
          {},
          {
            request_id: "test",
            type: "result",
            data: { name: "Test App", version: "1.0.0" },
          }
        );
      }
    );

    api.appInfo();

    expect(ipcRenderer.send).toHaveBeenCalledTimes(1);
    const [channel, payload] = ipcRenderer.send.mock.calls[0];
    expect(channel).toBe("desktop-backend-request");
    expect(payload.command).toBe("app_info");
    expect(typeof payload.request_id).toBe("string");
  });

  it("rejects error responses with the correct error code", async () => {
    expect(api).toBeDefined();

    ipcRenderer.once.mockImplementation(
      (_channel: string, cb: (event: unknown, response: unknown) => void) => {
        cb(
          {},
          {
            request_id: "test",
            type: "error",
            error: { code: "unknown_command", message: "Bad command" },
          }
        );
      }
    );

    await expect(api.health()).rejects.toThrow("Bad command");
  });

  it("uses unique request IDs for concurrent calls", () => {
    expect(api).toBeDefined();

    ipcRenderer.once.mockImplementation(() => {});

    api.health();
    api.appInfo();

    expect(ipcRenderer.send).toHaveBeenCalledTimes(2);
    const id1 = ipcRenderer.send.mock.calls[0][1].request_id;
    const id2 = ipcRenderer.send.mock.calls[1][1].request_id;
    expect(id1).not.toBe(id2);
  });
});
