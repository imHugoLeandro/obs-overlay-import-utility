/**
 * Preload script for the Electron desktop shell.
 *
 * Security rules enforced here:
 * - `contextIsolation` is enabled (this file runs in an isolated context).
 * - Only typed `health` and `appInfo` calls are exposed via `contextBridge`.
 * - Uses fixed IPC channels (`desktop:health`, `desktop:app-info`) via
 *   `ipcRenderer.invoke` — no dynamic channels, no raw IPC, no filesystem,
 *   no shell, no child_process access.
 * - No Node.js APIs are exposed to the renderer.
 */

import { contextBridge, ipcRenderer } from "electron";
import type {
  AppInfoData,
  HealthData,
} from "../types/api";

// ---------------------------------------------------------------------------
// Public API exposed to the renderer
// ---------------------------------------------------------------------------

/**
 * Typed API surface exposed to the renderer via `contextBridge`.
 *
 * Only `health` and `appInfo` are exposed.  There is no shell, file-read,
 * or generic function-call endpoint.
 */
const electronAPI = {
  /**
   * Query the Python backend's health endpoint.
   * Returns process metadata: status, pid, uptime, python version.
   */
  health: (): Promise<HealthData> => ipcRenderer.invoke("desktop:health"),

  /**
   * Query the Python backend's app_info endpoint.
   * Returns the application name and version.
   */
  appInfo: (): Promise<AppInfoData> => ipcRenderer.invoke("desktop:app-info"),
};

// Expose the API.  No other Electron or Node APIs are exposed.
contextBridge.exposeInMainWorld("electronAPI", electronAPI);
