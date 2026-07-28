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
 *   IDs and collection IDs plus safe display labels.
 * - `chooseOverlayFolder()` takes no parameters — the folder dialog is
 *   opened entirely in the Electron main process.
 */

import { contextBridge, ipcRenderer } from "electron";
import type {
  AppInfoData,
  ConvertResult,
  HealthData,
  ScanCollectionsResult,
  StreamlabsImportResult,
  AutomaticImportResult,
  DeviceRequirement,
  DeviceCandidate,
  DeviceApplyResult,
  ObsRunningResult,
  ActivateResult,
  ExportCollectionInfo,
  ExportDestinationInfo,
  ExportInventory,
  ExportResult,
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
   * Open a native folder dialog (no renderer arguments) and store the
   * selected folder in the Electron main-process selection store.
   *
   * The renderer never provides or receives a raw absolute path.
   * Returns only an opaque selection ID and a safe folder label.
   */
  chooseOverlayFolder: (): Promise<{
    selection_id: string;
    folder_label: string;
  }> => ipcRenderer.invoke("desktop:choose-overlay-folder"),

  /**
   * Open a native file dialog with a strict .overlay filter and store
   * the selected archive in the Electron main-process selection store.
   *
   * The renderer never provides or receives a raw absolute path.
   * Returns only an opaque selection ID and a safe archive label.
   */
  chooseStreamlabsOverlay: (): Promise<{
    selection_id: string;
    folder_label: string;
  }> => ipcRenderer.invoke("desktop:choose-streamlabs-overlay"),

  /**
   * Open a native folder dialog for automatic import and store the
   * selected folder in the Electron main-process selection store.
   */
  chooseAutomaticFolder: (): Promise<{
    selection_id: string;
    folder_label: string;
  }> => ipcRenderer.invoke("desktop:choose-automatic-folder"),

  /**
   * Scan the selected folder for OBS scene collections.
   * Returns detected collections with opaque collection IDs and safe
   * relative labels only.
   */
  scanCollections: (
    selectionId: string
  ): Promise<ScanCollectionsResult> =>
    ipcRenderer.invoke("desktop:scan-collections", { selection_id: selectionId }),

  /**
   * Select one detected collection by its opaque collection ID.
   * Verifies that the collection ID belongs to the selection.
   */
  chooseCollection: (
    selectionId: string,
    collectionId: string
  ): Promise<{ selection_id: string; collection_label: string }> =>
    ipcRenderer.invoke("desktop:choose-collection", {
      selection_id: selectionId,
      collection_id: collectionId,
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

  /**
   * Import a Streamlabs .overlay archive.
   * The archive path is resolved from the selection ID by Electron main.
   * Returns a customer-safe summary with collection name, canvas info,
   * and imported/skipped source counts.
   */
  importStreamlabs: (
    selectionId: string
  ): Promise<StreamlabsImportResult> =>
    ipcRenderer.invoke("desktop:import-streamlabs", {
      selection_id: selectionId,
    }),

  /**
   * Detect and import one supported package (portable/OBS/Streamlabs).
   * The folder path is resolved from the selection ID by Electron main.
   * Returns the package kind, collection name, canvas info, and errors.
   */
  automaticImport: (
    selectionId: string,
    strict: boolean,
    caseSensitive: boolean
  ): Promise<AutomaticImportResult> =>
    ipcRenderer.invoke("desktop:automatic-import", {
      selection_id: selectionId,
      strict,
      case_sensitive: caseSensitive,
    }),

  /**
   * List configurable device sources for an installed collection.
   * Returns requirement IDs, names, kinds, and source IDs — never raw
   * paths or arbitrary settings objects.
   */
  deviceRequirements: (
    collectionPath: string
  ): Promise<{ requirements: DeviceRequirement[]; count: number }> =>
    ipcRenderer.invoke("desktop:device-requirements", {
      collection_path: collectionPath,
    }),

  /**
   * List reusable local device settings.
   * Returns safe candidate labels and opaque candidate IDs — never raw
   * paths or arbitrary settings objects.
   */
  deviceCandidates: (
    obsScenesDirectory: string,
    excludeCollection?: string
  ): Promise<{ candidates: DeviceCandidate[]; count: number }> =>
    ipcRenderer.invoke("desktop:device-candidates", {
      obs_scenes_directory: obsScenesDirectory,
      exclude_collection: excludeCollection,
    }),

  /**
   * Apply selected device settings to an imported collection.
   * Choices are opaque candidate IDs or "disable".
   * Electron main resolves these to the actual settings before forwarding.
   */
  applyDeviceChoices: (
    collectionPath: string,
    choices: Record<string, unknown>
  ): Promise<DeviceApplyResult> =>
    ipcRenderer.invoke("desktop:apply-device-choices", {
      collection_path: collectionPath,
      choices,
    }),

  /**
   * Check whether OBS appears to be running.
   */
  obsRunning: (): Promise<ObsRunningResult> =>
    ipcRenderer.invoke("desktop:obs-running"),

  /**
   * Activate a collection in OBS via WebSocket (optional, explicit action).
   * The password is accepted only for this one request, forwarded once,
   * and never persisted.
   */
  activateCollection: (
    collectionName: string,
    password?: string
  ): Promise<ActivateResult> =>
    ipcRenderer.invoke("desktop:activate-collection", {
      collection_name: collectionName,
      password,
    }),

  /**
   * List OBS scene collections available for export.
   * Returns safe collection labels — never raw paths to the renderer.
   */
  listExportCollections: (
    obsScenesDirectory: string
  ): Promise<{ collections: ExportCollectionInfo[]; count: number }> =>
    ipcRenderer.invoke("desktop:list-export-collections", {
      obs_scenes_directory: obsScenesDirectory,
    }),

  /**
   * Open a native folder dialog for the export destination.
   * Returns the destination path (to Electron main only) and a safe label.
   */
  chooseExportDestination: (): Promise<ExportDestinationInfo> =>
    ipcRenderer.invoke("desktop:choose-export-destination"),

  /**
   * Build a frozen, backend-held export plan.
   * Returns a sanitized inventory view with an opaque plan ID.
   * The renderer cannot reconstruct, modify, or submit a replacement plan.
   */
  buildExportPlan: (
    collectionPath: string,
    destination: string,
    compressed: boolean
  ): Promise<ExportInventory> =>
    ipcRenderer.invoke("desktop:build-export-plan", {
      collection_path: collectionPath,
      destination,
      compressed,
    }),

  /**
   * Return a sanitized inventory view for an existing plan.
   * Expired or unknown plan IDs fail safely.
   */
  exportInventory: (planId: string): Promise<ExportInventory> =>
    ipcRenderer.invoke("desktop:export-inventory", {
      plan_id: planId,
    }),

  /**
   * Execute a frozen export plan by opaque ID.
   * The backend revalidates and executes the exact frozen plan.
   * Unknown, expired, already-executed, or altered plans fail safely.
   * Successful plans become idempotent.
   */
  confirmExport: (planId: string): Promise<ExportResult> =>
    ipcRenderer.invoke("desktop:confirm-export", {
      plan_id: planId,
    }),
};

// Expose the API.  No other Electron or Node APIs are exposed.
contextBridge.exposeInMainWorld("electronAPI", electronAPI);
