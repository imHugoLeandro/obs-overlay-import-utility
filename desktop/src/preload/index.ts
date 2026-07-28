/**
 * Preload script for the Electron desktop shell.
 *
 * Security rules enforced here:
 * - `contextIsolation` is enabled (this file runs in an isolated context).
 * - Only typed, finite APIs are exposed via `contextBridge`.
 * - Uses fixed IPC channels via `ipcRenderer.invoke` — no dynamic channels,
 *   no raw IPC, no filesystem, no shell, no child_process access.
 * - No Node.js APIs are exposed to the renderer.
 * - The renderer never receives raw absolute paths — only opaque IDs.
 * - `chooseOverlayFolder()` takes no parameters — the folder dialog is
 *   opened entirely in the Electron main process.
 * - All device/export/workflow APIs accept only opaque IDs, never paths.
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
  ResizeScope,
  ResizeMode,
  ResizeSourceChoice,
  ResizeResult,
  ResizeCollectionInfo,
} from "../types/api";

// ---------------------------------------------------------------------------
// Public API exposed to the renderer
// ---------------------------------------------------------------------------

const electronAPI = {
  health: (): Promise<HealthData> => ipcRenderer.invoke("desktop:health"),

  appInfo: (): Promise<AppInfoData> => ipcRenderer.invoke("desktop:app-info"),

  /**
   * Open a native folder dialog (no renderer arguments).
   * Returns only an opaque selection ID and a safe folder label.
   */
  chooseOverlayFolder: (): Promise<{
    selection_id: string;
    folder_label: string;
  }> => ipcRenderer.invoke("desktop:choose-overlay-folder"),

  /**
   * Open a native file dialog with a strict .overlay filter.
   * Returns only an opaque selection ID and a safe archive label.
   * No renderer arguments accepted.
   */
  chooseStreamlabsOverlay: (): Promise<{
    selection_id: string;
    folder_label: string;
  }> => ipcRenderer.invoke("desktop:choose-streamlabs-overlay"),

  /**
   * Open a native folder dialog for automatic import.
   * Returns only an opaque selection ID and a safe folder label.
   * No renderer arguments accepted.
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
   * Returns an opaque installation_id on success.
   */
  importStreamlabs: (
    selectionId: string
  ): Promise<StreamlabsImportResult> =>
    ipcRenderer.invoke("desktop:import-streamlabs", {
      selection_id: selectionId,
    }),

  /**
   * Detect and import one supported package.
   * Returns an opaque installation_id on success.
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
   * Takes only an opaque installation_id — never a raw path.
   */
  deviceRequirements: (
    installationId: string
  ): Promise<{ requirements: DeviceRequirement[]; count: number }> =>
    ipcRenderer.invoke("desktop:device-requirements", {
      installation_id: installationId,
    }),

  /**
   * List reusable local device settings for a given installation.
   * Takes only an opaque installation_id — never a raw path.
   */
  deviceCandidates: (
    installationId: string
  ): Promise<{ candidates: DeviceCandidate[]; count: number }> =>
    ipcRenderer.invoke("desktop:device-candidates", {
      installation_id: installationId,
    }),

  /**
   * Apply selected device settings to an installed collection.
   * Takes only an opaque installation_id — never a raw path.
   * Choices are opaque candidate IDs resolved by Electron main.
   */
  applyDeviceChoices: (
    installationId: string,
    choices: Record<string, unknown>
  ): Promise<DeviceApplyResult> =>
    ipcRenderer.invoke("desktop:apply-device-choices", {
      installation_id: installationId,
      choices,
    }),

  /**
   * Check whether OBS appears to be running.
   */
  obsRunning: (): Promise<ObsRunningResult> =>
    ipcRenderer.invoke("desktop:obs-running"),

  /**
   * Activate a collection in OBS via WebSocket (optional, explicit action).
   * Takes only an opaque installation_id — never a raw collection name or path.
   * The password is accepted only for this one request, forwarded once,
   * and never persisted.
   */
  activateCollection: (
    installationId: string,
    password?: string
  ): Promise<ActivateResult> =>
    ipcRenderer.invoke("desktop:activate-collection", {
      installation_id: installationId,
      password,
    }),

  /**
   * List OBS scene collections available for export.
   * Takes no renderer path — Electron main resolves the OBS scenes directory.
   * Returns opaque collection IDs and safe labels.
   */
  listExportCollections: (): Promise<{
    collections: ExportCollectionInfo[];
    count: number;
  }> => ipcRenderer.invoke("desktop:list-export-collections"),

  /**
   * Open a native folder dialog for the export destination.
   * Returns an opaque destination_id and a safe label — never a raw path.
   */
  chooseExportDestination: (): Promise<ExportDestinationInfo> =>
    ipcRenderer.invoke("desktop:choose-export-destination"),

  /**
   * Build a frozen, backend-held export plan.
   * Takes only opaque collection_id and destination_id — never raw paths.
   * Returns a sanitized inventory view with an opaque plan_id.
   */
  buildExportPlan: (
    collectionId: string,
    destinationId: string,
    compressed: boolean
  ): Promise<ExportInventory> =>
    ipcRenderer.invoke("desktop:build-export-plan", {
      collection_id: collectionId,
      destination_id: destinationId,
      compressed,
    }),

  /**
   * Return a sanitized inventory view for an existing plan.
   */
  exportInventory: (planId: string): Promise<ExportInventory> =>
    ipcRenderer.invoke("desktop:export-inventory", {
      plan_id: planId,
    }),

  /**
   * Execute a frozen export plan by opaque plan_id.
   */
  confirmExport: (planId: string): Promise<ExportResult> =>
    ipcRenderer.invoke("desktop:confirm-export", {
      plan_id: planId,
    }),

  /**
   * Scan a folder for OBS collections with canvas info for resize.
   * Returns opaque collection IDs and safe labels only.
   */
  scanResizeCollections: (selectionId: string): Promise<{
    collections: ResizeCollectionInfo[];
    count: number;
  }> =>
    ipcRenderer.invoke("desktop:scan-resize-collections", {
      selection_id: selectionId,
    }),

  /**
   * Choose a collection for resize by opaque collection ID.
   */
  chooseResizeCollection: (
    selectionId: string,
    collectionId: string
  ): Promise<{ collection_id: string; label: string }> =>
    ipcRenderer.invoke("desktop:choose-resize-collection", {
      selection_id: selectionId,
      collection_id: collectionId,
    }),

  /**
   * List UUID-backed source choices for Source-scope resize.
   */
  resizeSourceChoices: (
    selectionId: string
  ): Promise<{ choices: ResizeSourceChoice[]; count: number }> =>
    ipcRenderer.invoke("desktop:resize-source-choices", {
      selection_id: selectionId,
    }),

  /**
   * List scene names for Scene-scope resize.
   */
  resizeSceneChoices: (
    selectionId: string
  ): Promise<{ scenes: string[]; count: number }> =>
    ipcRenderer.invoke("desktop:resize-scene-choices", {
      selection_id: selectionId,
    }),

  /**
   * Preview an offline resize (validates inputs, returns what would change).
   */
  previewResize: (
    selectionId: string,
    scope: ResizeScope,
    mode: ResizeMode,
    targetWidth: number,
    targetHeight: number,
    selectedName?: string,
    selectedUuid?: string
  ): Promise<{ valid: boolean; error: string | null; source_width: number; source_height: number; changed_items: number }> =>
    ipcRenderer.invoke("desktop:preview-resize", {
      selection_id: selectionId,
      scope,
      mode,
      target_width: targetWidth,
      target_height: targetHeight,
      selected_name: selectedName,
      selected_uuid: selectedUuid,
    }),

  /**
   * Execute an offline resize. Creates a backup before writing.
   */
  applyResize: (
    selectionId: string,
    scope: ResizeScope,
    mode: ResizeMode,
    targetWidth: number,
    targetHeight: number,
    selectedName?: string,
    selectedUuid?: string
  ): Promise<ResizeResult> =>
    ipcRenderer.invoke("desktop:apply-resize", {
      selection_id: selectionId,
      scope,
      mode,
      target_width: targetWidth,
      target_height: targetHeight,
      selected_name: selectedName,
      selected_uuid: selectedUuid,
    }),

  /**
   * Undo a resize by restoring a backup.
   * Takes only opaque IDs — never a raw backup path.
   */
  undoResize: (
    selectionId: string,
    undoId: string
  ): Promise<{ success: boolean; error: string | null }> =>
    ipcRenderer.invoke("desktop:undo-resize", {
      selection_id: selectionId,
      undo_id: undoId,
    }),
};

// Expose the API.  No other Electron or Node APIs are exposed.
contextBridge.exposeInMainWorld("electronAPI", electronAPI);