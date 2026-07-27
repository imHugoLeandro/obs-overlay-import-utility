/**
 * Preload script for the Electron desktop shell.
 *
 * Security rules enforced here:
 * - `contextIsolation` is enabled (this file runs in an isolated context).
 * - Only typed, finite APIs are exposed via `contextBridge`.
 * - Uses fixed IPC channels via `ipcRenderer.invoke` — no dynamic channels,
 *   no raw IPC, no filesystem, no shell, no child_process access.
 * - No Node.js APIs are exposed to the renderer.
 * - The renderer never receives raw absolute paths — only opaque selection
 *   IDs and safe display labels.
 */

import { contextBridge, ipcRenderer } from "electron";
import type {
  AppInfoData,
  ChooseCollectionResult,
  ConvertResult,
  HealthData,
  ScanCollectionsResult,
} from "../types/api";

// ---------------------------------------------------------------------------
// Public API exposed to the renderer
// ---------------------------------------------------------------------------

/**
 * Typed API surface exposed to the renderer via `contextBridge`.
 *
 * Only the finite set of commands below is exposed.  There is no shell,
 * file-read, or generic function-call endpoint.
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

  /**
   * Store an overlay folder path (resolved by the main process folder
   * dialog) and return an opaque selection ID plus a safe label.
   *
   * The renderer never sees the raw absolute path — only the opaque
   * selection ID and the folder basename label.
   */
  chooseFolder: (folderPath: string): Promise<{
    selection_id: string;
    folder_label: string;
  }> => ipcRenderer.invoke("desktop:choose-folder", { folder_path: folderPath }),

  /**
   * Scan the selected folder for OBS scene collections.
   * Returns detected collections with safe relative labels only.
   */
  scanCollections: (
    selectionId: string
  ): Promise<ScanCollectionsResult> =>
    ipcRenderer.invoke("desktop:scan-collections", { selection_id: selectionId }),

  /**
   * Select one detected collection by its index.
   * Returns a safe collection label.
   */
  chooseCollection: (
    selectionId: string,
    collectionIndex: number
  ): Promise<ChooseCollectionResult> =>
    ipcRenderer.invoke("desktop:choose-collection", {
      selection_id: selectionId,
      collection_index: collectionIndex,
    }),

  /**
   * Run path-fix conversion on the selected collection.
   * The original collection is never modified.
   * Returns a structured result with success/failure details.
   */
  convertCollection: (
    selectionId: string,
    strict: boolean,
    caseSensitive: boolean
  ): Promise<ConvertResult> =>
    ipcRenderer.invoke("desktop:convert-collection", {
      selection_id: selectionId,
      strict,
      case_sensitive: caseSensitive,
    }),
};

// Expose the API.  No other Electron or Node APIs are exposed.
contextBridge.exposeInMainWorld("electronAPI", electronAPI);
