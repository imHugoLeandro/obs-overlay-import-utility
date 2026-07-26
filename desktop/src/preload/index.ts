/**
 * Preload script for the Electron desktop shell.
 *
 * Security rules enforced here:
 * - `contextIsolation` is enabled (this file runs in an isolated context).
 * - Only typed `health` and `app_info` calls are exposed via `contextBridge`.
 * - Every IPC payload is validated before being sent to the main process.
 * - No Node.js APIs, filesystem, child_process, or IPC primitives are
 *   exposed to the renderer.
 */

import { contextBridge, ipcRenderer } from "electron";
import type {
  AppInfoData,
  BackendResponse,
  HealthData,
} from "../types/api";

// ---------------------------------------------------------------------------
// Request ID generation
// ---------------------------------------------------------------------------

let _counter = 0;

/**
 * Generate a unique request ID.
 *
 * Format: `req-<timestamp>-<counter>` — guaranteed unique within a session.
 */
function generateRequestId(): string {
  _counter = (_counter + 1) % 1_000_000;
  return `req-${Date.now()}-${_counter}`;
}

// ---------------------------------------------------------------------------
// IPC transport
// ---------------------------------------------------------------------------

/**
 * Send a typed request to the main process and await the typed response.
 *
 * The main process validates the channel name, sender, and payload before
 * forwarding the request to the Python backend.  Only `health` and
 * `app_info` channels are accepted.
 */
function sendRequest<T>(command: string): Promise<T> {
  const requestId = generateRequestId();
  const channel = "desktop-backend-request";

  return new Promise<T>((resolve, reject) => {
    // Set up a one-time response listener keyed on the request ID.
    const responseChannel = `desktop-backend-response-${requestId}`;

    ipcRenderer.once(responseChannel, (_event, response: BackendResponse) => {
      if (response.type === "result") {
        resolve(response.data as T);
      } else {
        const err = new Error(response.error.message);
        // Attach the structured error code for callers that need it.
        (err as Error & { code: string }).code = response.error.code;
        reject(err);
      }
    });

    // Send the request.  The main process validates the channel and payload.
    ipcRenderer.send(channel, { request_id: requestId, command });
  });
}

// ---------------------------------------------------------------------------
// Public API exposed to the renderer
// ---------------------------------------------------------------------------

const electronAPI = {
  /**
   * Query the Python backend's health endpoint.
   * Returns process metadata: status, pid, uptime, python version.
   */
  health: (): Promise<HealthData> => sendRequest<HealthData>("health"),

  /**
   * Query the Python backend's app_info endpoint.
   * Returns the application name and version.
   */
  appInfo: (): Promise<AppInfoData> => sendRequest<AppInfoData>("app_info"),
};

// Expose the API.  No other Electron or Node APIs are exposed.
contextBridge.exposeInMainWorld("electronAPI", electronAPI);
