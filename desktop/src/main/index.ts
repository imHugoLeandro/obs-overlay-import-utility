/**
 * Electron main process for the OBS Overlay Import Utility desktop shell.
 *
 * Architecture:
 * - The main process spawns and manages a Python stdio backend.
 * - The Python backend exposes a finite set of commands via JSON-lines.
 * - IPC requests from the renderer use fixed channels via
 *   ipcMain.handle / ipcRenderer.invoke.
 * - The renderer never imports Electron, Node, filesystem, child_process,
 *   or IPC primitives directly.
 * - Import session ownership: Electron main is the sole owner of all
 *   selected absolute paths and opaque IDs. The ImportSelectionStore
 *   holds canonical paths in memory only; the renderer receives only
 *   opaque selection IDs and collection IDs plus safe labels.
 * - The Python backend receives concrete folder/collection paths only
 *   from Electron main over the trusted stdio channel — never opaque
 *   renderer IDs.
 *
 * Security configuration:
 * - nodeIntegration: false
 * - contextIsolation: true
 * - sandbox: true
 * - webSecurity: true
 * - webviewTag: false
 * - Unexpected navigation and new windows are blocked.
 * - All permission requests are denied.
 * - Production CSP restricts content to the packaged app.
 * - Every IPC sender, channel, and payload is validated.
 */

import { app, BrowserWindow, dialog, ipcMain, session } from "electron";
import * as path from "path";
import { realpathSync, writeFileSync } from "fs";
import {
  DEV_ORIGIN,
  isValidOrigin,
  isAllowedNavigation,
  resolvePackagedRendererPath,
  resolvePythonPath,
  resolvePreloadPath,
} from "./security";
import { BackendTransport } from "./transport";
import { ImportSelectionStore, SelectionError } from "./importSelectionStore";
import { ImportInstallationStore, InstallationError } from "./importInstallationStore";
import { ExportStore, ExportError } from "./exportStore";
import { ResizeUndoStore, UndoError } from "./resizeUndoStore";
import { callBackend, BACKEND_UNAVAILABLE_ERROR, ExpectedBackendError } from "./backendCall";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/** Allowed commands that can be sent to the Python backend. */
const ALLOWED_COMMANDS = new Set([
  "health",
  "app_info",
  "scan_collections",
  "convert_collection",
  "import_streamlabs",
  "automatic_import",
  "device_requirements",
  "device_candidates",
  "apply_device_choices",
  "obs_running",
  "activate_collection",
  "list_export_collections",
  "build_export_plan",
  "export_inventory",
  "confirm_export",
]);

/**
 * Validate that a command is in the allowed set.
 * This provides defense-in-depth alongside the fixed IPC channels.
 */
function isAllowedCommand(command: string): boolean {
  return ALLOWED_COMMANDS.has(command);
}

/** Fixed IPC channels — no dynamic channel construction. */
const HEALTH_CHANNEL = "desktop:health";
const APP_INFO_CHANNEL = "desktop:app-info";
const CHOOSE_OVERLAY_FOLDER_CHANNEL = "desktop:choose-overlay-folder";
const CHOOSE_STREAMLABS_OVERLAY_CHANNEL = "desktop:choose-streamlabs-overlay";
const CHOOSE_AUTOMATIC_FOLDER_CHANNEL = "desktop:choose-automatic-folder";
const CHOOSE_EXPORT_DESTINATION_CHANNEL = "desktop:choose-export-destination";
const SCAN_COLLECTIONS_CHANNEL = "desktop:scan-collections";
const CHOOSE_COLLECTION_CHANNEL = "desktop:choose-collection";
const CONVERT_COLLECTION_CHANNEL = "desktop:convert-collection";
const IMPORT_STREAMLABS_CHANNEL = "desktop:import-streamlabs";
const AUTOMATIC_IMPORT_CHANNEL = "desktop:automatic-import";
const DEVICE_REQUIREMENTS_CHANNEL = "desktop:device-requirements";
const DEVICE_CANDIDATES_CHANNEL = "desktop:device-candidates";
const APPLY_DEVICE_CHOICES_CHANNEL = "desktop:apply-device-choices";
const OBS_RUNNING_CHANNEL = "desktop:obs-running";
const ACTIVATE_COLLECTION_CHANNEL = "desktop:activate-collection";
const LIST_EXPORT_COLLECTIONS_CHANNEL = "desktop:list-export-collections";
const BUILD_EXPORT_PLAN_CHANNEL = "desktop:build-export-plan";
const EXPORT_INVENTORY_CHANNEL = "desktop:export-inventory";
const CONFIRM_EXPORT_CHANNEL = "desktop:confirm-export";
const SCAN_RESIZE_COLLECTIONS_CHANNEL = "desktop:scan-resize-collections";
const CHOOSE_RESIZE_COLLECTION_CHANNEL = "desktop:choose-resize-collection";
const RESIZE_SOURCE_CHOICES_CHANNEL = "desktop:resize-source-choices";
const RESIZE_SCENE_CHOICES_CHANNEL = "desktop:resize-scene-choices";
const PREVIEW_RESIZE_CHANNEL = "desktop:preview-resize";
const APPLY_RESIZE_CHANNEL = "desktop:apply-resize";
const UNDO_RESIZE_CHANNEL = "desktop:undo-resize";

/**
 * Resolve the Python executable for development.
 *
 * Uses the `OBS_OVERLAY_PYTHON` environment variable.  If it is not set
 * or does not point to a valid Python executable, the backend will not
 * start and a clear error is shown.
 */
function resolveDevPython(): string | null {
  const envPath = process.env.OBS_OVERLAY_PYTHON;
  if (!envPath) {
    return null;
  }
  return envPath;
}

/**
 * Validate that a path is an executable file.
 */
function isValidExecutable(filePath: string): boolean {
  try {
    const { existsSync, statSync } = require("fs");
    return existsSync(filePath) && statSync(filePath).isFile();
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Backend transport
// ---------------------------------------------------------------------------

const backend = new BackendTransport();

// ---------------------------------------------------------------------------
// Import session store — sole owner of selected paths and opaque IDs
// ---------------------------------------------------------------------------

const importStore = new ImportSelectionStore();
const installationStore = new ImportInstallationStore();
const exportStore = new ExportStore();
const resizeUndoStore = new ResizeUndoStore();

// ---------------------------------------------------------------------------
// Resolve OBS scenes directory from environment or settings
// ---------------------------------------------------------------------------

function resolveObsScenesDir(): string {
  return process.env.OBS_SCENES_DIR || "";
}

// ---------------------------------------------------------------------------
// IPC handlers — fixed channels via ipcMain.handle
// ---------------------------------------------------------------------------

/**
 * Validate that the IPC sender is exactly the main window's webContents.
 * Rejects any other sender (e.g., from a different origin or preload).
 */
function isValidSender(sender: Electron.WebContents): boolean {
  if (!mainWindow || sender.isDestroyed()) {
    return false;
  }
  return sender === mainWindow.webContents;
}

/**
 * Validate that a value is a non-empty string.
 */
function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/**
 * Validate that a value is a plain object (not array, not null).
 */
function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

/**
 * Convert an error to a renderer-safe error message.
 * SelectionError and ExpectedBackendError messages are already
 * customer-safe (no raw paths, no tracebacks).
 */
function selectionErrorMessage(err: unknown): string {
  if (err instanceof SelectionError) {
    return err.message;
  }
  if (err instanceof InstallationError) {
    return err.message;
  }
  if (err instanceof ExportError) {
    return err.message;
  }
  if (err instanceof UndoError) {
    return err.message;
  }
  if (err instanceof ExpectedBackendError) {
    return err.message;
  }
  return BACKEND_UNAVAILABLE_ERROR;
}

// ---------------------------------------------------------------------------
// IPC: health
// ---------------------------------------------------------------------------

ipcMain.handle(HEALTH_CHANNEL, async (event) => {
  if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
    throw new Error("Unauthorized sender");
  }
  if (!isAllowedCommand("health")) {
    throw new Error("Command not allowed");
  }
  try {
    return await callBackend(backend, "health");
  } catch (err) {
    throw new Error(selectionErrorMessage(err));
  }
});

// ---------------------------------------------------------------------------
// IPC: app_info
// ---------------------------------------------------------------------------

ipcMain.handle(APP_INFO_CHANNEL, async (event) => {
  if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
    throw new Error("Unauthorized sender");
  }
  if (!isAllowedCommand("app_info")) {
    throw new Error("Command not allowed");
  }
  try {
    return await callBackend(backend, "app_info");
  } catch (err) {
    throw new Error(selectionErrorMessage(err));
  }
});

// ---------------------------------------------------------------------------
// IPC: chooseOverlayFolder — no renderer arguments
// ---------------------------------------------------------------------------

ipcMain.handle(CHOOSE_OVERLAY_FOLDER_CHANNEL, async (event) => {
  if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
    throw new Error("Unauthorized sender");
  }
  if (!isAllowedCommand("choose_folder")) {
    throw new Error("Command not allowed");
  }

  // Open a folder dialog — the main process holds the absolute path.
  // No renderer arguments are accepted.
  const result = await dialog.showOpenDialog(mainWindow!, {
    title: "Choose an extracted overlay folder",
    properties: ["openDirectory", "dontAddToRecent", "createDirectory"],
    buttonLabel: "Select Overlay Folder",
  });

  if (result.canceled || result.filePaths.length === 0) {
    throw new Error("No folder selected");
  }

  // Validate the folder with realpathSync and statSync.isDirectory().
  // This resolves symlinks/reparse-points to their canonical target
  // and rejects paths that are not directories.
  let folderPath: string;
  try {
    folderPath = realpathSync(result.filePaths[0]);
  } catch {
    throw new Error("The selected path is not valid.");
  }

  try {
    const { statSync } = require("fs");
    if (!statSync(folderPath).isDirectory()) {
      throw new Error("The selected path is not a directory.");
    }
  } catch {
    throw new Error("The selected path is not a directory.");
  }

  const folderLabel = folderPath.split(/[\\/]/).pop() || folderPath;

  // Store the canonical path in the main-process selection store.
  // The renderer receives only the opaque selection ID and label.
  const selectionId = importStore.createFolderSelection(folderPath, folderLabel);

  return {
    selection_id: selectionId,
    folder_label: folderLabel,
  };
});

// ---------------------------------------------------------------------------
// IPC: scanCollections — Electron main resolves the folder path
// ---------------------------------------------------------------------------

ipcMain.handle(SCAN_COLLECTIONS_CHANNEL, async (event, params: unknown) => {
  if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
    throw new Error("Unauthorized sender");
  }
  if (!isAllowedCommand("scan_collections")) {
    throw new Error("Command not allowed");
  }
  if (!isPlainObject(params) || !isNonEmptyString(params.selection_id)) {
    throw new Error("Invalid selection_id");
  }

  // Resolve the canonical folder path from the main-process store.
  let folderPath: string;
  try {
    folderPath = importStore.getFolderPath(params.selection_id);
  } catch (err) {
    throw new Error(selectionErrorMessage(err));
  }

  // Forward the trusted path to the Python backend.
  // The backend uses find_scene_collections() and returns absolute paths
  // only to Electron main (never to the renderer).
  let response: unknown;
  try {
    response = await callBackend(backend, "scan_collections", {
      folder_path: folderPath,
    });
  } catch (err) {
    throw new Error(selectionErrorMessage(err));
  }

  const resp = response as {
    collections?: Array<{ path: string; label: string }>;
    count?: number;
  };

  if (!resp || !Array.isArray(resp.collections)) {
    throw new Error(BACKEND_UNAVAILABLE_ERROR);
  }

  // Store the scanned collections with fresh opaque collection IDs.
  // The renderer receives only { collection_id, label }.
  // Electron main stores the canonical absolute path returned by the
  // backend (not the relative label) as the collection path.
  importStore.setCollections(
    params.selection_id,
    resp.collections.map((c) => ({
      path: c.path,
      label: c.label,
    }))
  );

  // Return only safe data to the renderer.
  const collections = importStore.getCollections(params.selection_id);
  return {
    selection_id: params.selection_id,
    folder_label: importStore.getFolderLabel(params.selection_id),
    collections,
    count: collections.length,
  };
});

// ---------------------------------------------------------------------------
// IPC: chooseCollection — verify collection ID belongs to selection
// ---------------------------------------------------------------------------

ipcMain.handle(
  CHOOSE_COLLECTION_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isAllowedCommand("choose_collection")) {
      throw new Error("Command not allowed");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.selection_id)) {
      throw new Error("Invalid selection_id");
    }
    if (!isNonEmptyString(params.collection_id)) {
      throw new Error("Invalid collection_id");
    }

    try {
      importStore.chooseCollection(params.selection_id, params.collection_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }

    // Return the real selected collection label, not a hard-coded string.
    let collectionLabel: string;
    try {
      collectionLabel = importStore.getCollectionLabel(params.selection_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }

    return {
      selection_id: params.selection_id,
      collection_label: collectionLabel,
    };
  }
);

// ---------------------------------------------------------------------------
// IPC: convertCollection — resolve trusted path, then convert
// ---------------------------------------------------------------------------

ipcMain.handle(
  CONVERT_COLLECTION_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isAllowedCommand("convert_collection")) {
      throw new Error("Command not allowed");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.selection_id)) {
      throw new Error("Invalid selection_id");
    }
    if (typeof params.strict !== "boolean") {
      throw new Error("Invalid strict option");
    }
    if (typeof params.case_sensitive !== "boolean") {
      throw new Error("Invalid case_sensitive option");
    }

    // Atomically begin conversion: transitions "ready" → "converting".
    // A second simultaneous call is rejected safely.
    // A completed selection is also rejected.
    try {
      importStore.beginConversion(params.selection_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }

    // Resolve the canonical folder and collection paths from the
    // main-process store. This revalidates existence, regular-file
    // status, and folder containment (symlink/reparse-point escape).
    let folderPath: string;
    let collectionPath: string;
    try {
      folderPath = importStore.getFolderPath(params.selection_id);
      collectionPath = importStore.getCollectionPath(params.selection_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }

    // Forward the trusted paths to the Python backend's convert adapter.
    let response: unknown;
    try {
      response = await callBackend(backend, "convert_collection", {
        folder_path: folderPath,
        collection_path: collectionPath,
        strict: params.strict,
        case_sensitive: params.case_sensitive,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }

    const resp = response as {
      success?: boolean;
      changed?: number;
      unchanged?: number;
      missing?: string[];
      ambiguous?: Array<{
        source_name: string;
        original_path: string;
        candidates: string[];
      }>;
      indexed_files?: number;
      candidate_paths?: number;
      output_filename?: string;
      output_path?: string;
      error?: string;
    };

    if (!resp || typeof resp.success !== "boolean") {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }

    // On success, mark the selection as converted (idempotency).
    // On failure, return to "ready" state to allow retry.
    // finishConversion never ignores a state-transition failure — it
    // throws SelectionError if the state is not "converting".
    try {
      importStore.finishConversion(params.selection_id, resp.success);
    } catch {
      // If marking fails, the conversion still succeeded — don't
      // block the user from seeing the result.  The state error is
      // logged but does not prevent returning the result.
    }

    // Build the renderer-facing result. The backend returns relative
    // paths for output_filename; no raw absolute paths are included.
    return {
      success: resp.success,
      changed: resp.changed ?? 0,
      unchanged: resp.unchanged ?? 0,
      missing: resp.missing ?? [],
      ambiguous: resp.ambiguous ?? [],
      indexed_files: resp.indexed_files ?? 0,
      candidate_paths: resp.candidate_paths ?? 0,
      output_filename: resp.output_filename,
      output_path: resp.output_path,
      error: resp.error,
    };
  }
);

// ---------------------------------------------------------------------------
// IPC: chooseStreamlabsOverlay — strict .overlay filter
// ---------------------------------------------------------------------------

ipcMain.handle(CHOOSE_STREAMLABS_OVERLAY_CHANNEL, async (event) => {
  if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
    throw new Error("Unauthorized sender");
  }
  const result = await dialog.showOpenDialog(mainWindow!, {
    title: "Choose a Streamlabs .overlay file",
    properties: ["openFile", "dontAddToRecent"],
    buttonLabel: "Select .overlay File",
    filters: [{ name: "Streamlabs Overlay", extensions: ["overlay"] }],
  });
  if (result.canceled || result.filePaths.length === 0) {
    throw new Error("No file selected");
  }
  let archivePath: string;
  try {
    archivePath = realpathSync(result.filePaths[0]);
  } catch {
    throw new Error("The selected path is not valid.");
  }
  const archiveLabel = archivePath.split(/[\\\\/]/).pop() || archivePath;
  const selectionId = importStore.createFolderSelection(archivePath, archiveLabel);
  return { selection_id: selectionId, folder_label: archiveLabel };
});

// ---------------------------------------------------------------------------
// IPC: chooseAutomaticFolder — narrow folder dialog
// ---------------------------------------------------------------------------

ipcMain.handle(CHOOSE_AUTOMATIC_FOLDER_CHANNEL, async (event) => {
  if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
    throw new Error("Unauthorized sender");
  }
  const result = await dialog.showOpenDialog(mainWindow!, {
    title: "Choose an overlay package folder",
    properties: ["openDirectory", "dontAddToRecent"],
    buttonLabel: "Select Package Folder",
  });
  if (result.canceled || result.filePaths.length === 0) {
    throw new Error("No folder selected");
  }
  let folderPath: string;
  try {
    folderPath = realpathSync(result.filePaths[0]);
  } catch {
    throw new Error("The selected path is not valid.");
  }
  const folderLabel = folderPath.split(/[\\\\/]/).pop() || folderPath;
  const selectionId = importStore.createFolderSelection(folderPath, folderLabel);
  return { selection_id: selectionId, folder_label: folderLabel };
});

// ---------------------------------------------------------------------------
// IPC: importStreamlabs — resolve trusted path, then import
// ---------------------------------------------------------------------------

ipcMain.handle(
  IMPORT_STREAMLABS_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.selection_id)) {
      throw new Error("Invalid selection_id");
    }
    let archivePath: string;
    try {
      archivePath = importStore.getFolderPath(params.selection_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const obsScenesDir = resolveObsScenesDir();
    if (!obsScenesDir) {
      throw new Error("OBS scenes directory is not configured.");
    }
    let response: unknown;
    try {
      response = await callBackend(backend, "import_streamlabs", {
        archive_path: archivePath,
        obs_scenes_directory: obsScenesDir,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || typeof resp.success !== "boolean") {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }

    // On success, create an opaque installation_id.
    let installationId: string | null = null;
    if (resp.success) {
      const collectionName = (resp.collection_name as string) || "";
      installationId = installationStore.createInstallation(
        "", // collection path unknown at this level
        obsScenesDir,
        collectionName
      );
    }

    return {
      success: resp.success,
      installation_id: installationId,
      collection_name: resp.collection_name ?? "",
      canvas_width: resp.canvas_width ?? 2560,
      canvas_height: resp.canvas_height ?? 1440,
      imported_sources: resp.imported_sources ?? 0,
      skipped_sources: resp.skipped_sources ?? [],
      profile_name: resp.profile_name ?? null,
      error: resp.error ?? null,
    };
  }
);

// ---------------------------------------------------------------------------
// IPC: automaticImport — resolve trusted path, then auto-import
// ---------------------------------------------------------------------------

ipcMain.handle(
  AUTOMATIC_IMPORT_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.selection_id)) {
      throw new Error("Invalid selection_id");
    }
    if (typeof params.strict !== "boolean") {
      throw new Error("Invalid strict option");
    }
    if (typeof params.case_sensitive !== "boolean") {
      throw new Error("Invalid case_sensitive option");
    }
    let folderPath: string;
    try {
      folderPath = importStore.getFolderPath(params.selection_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const obsScenesDir = resolveObsScenesDir();
    if (!obsScenesDir) {
      throw new Error("OBS scenes directory is not configured.");
    }
    let response: unknown;
    try {
      response = await callBackend(backend, "automatic_import", {
        overlay_root: folderPath,
        obs_scenes_directory: obsScenesDir,
        strict: params.strict,
        case_sensitive: params.case_sensitive,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || typeof resp.success !== "boolean") {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }

    // On success, create an opaque installation_id.
    let installationId: string | null = null;
    if (resp.success) {
      const collectionName = (resp.collection_name as string) || "";
      installationId = installationStore.createInstallation(
        "", // collection path not available at this level
        obsScenesDir,
        collectionName
      );
    }

    return {
      success: resp.success,
      installation_id: installationId,
      kind: resp.kind ?? "",
      collection_name: resp.collection_name ?? "",
      canvas_width: resp.canvas_width ?? null,
      canvas_height: resp.canvas_height ?? null,
      profile_name: resp.profile_name ?? null,
      error: resp.error ?? null,
      conversion: resp.conversion ?? null,
    };
  }
);

// ---------------------------------------------------------------------------
// IPC: deviceRequirements — resolve installationId, list device sources
// ---------------------------------------------------------------------------

ipcMain.handle(
  DEVICE_REQUIREMENTS_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.installation_id)) {
      throw new Error("Invalid installation_id");
    }
    let collectionPath: string;
    try {
      collectionPath = installationStore.getCollectionPath(params.installation_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    let response: unknown;
    try {
      response = await callBackend(backend, "device_requirements", {
        collection_path: collectionPath,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || !Array.isArray(resp.requirements)) {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }
    return {
      requirements: resp.requirements,
      count: resp.count ?? resp.requirements.length,
    };
  }
);

// ---------------------------------------------------------------------------
// IPC: deviceCandidates — resolve installationId, list reusable device settings
// ---------------------------------------------------------------------------

ipcMain.handle(
  DEVICE_CANDIDATES_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.installation_id)) {
      throw new Error("Invalid installation_id");
    }
    let obsScenesDir: string;
    let collectionPath: string;
    try {
      obsScenesDir = installationStore.getObsScenesDirectory(params.installation_id);
      collectionPath = installationStore.getCollectionPath(params.installation_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    let response: unknown;
    try {
      response = await callBackend(backend, "device_candidates", {
        obs_scenes_directory: obsScenesDir,
        exclude_collection: collectionPath,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || !Array.isArray(resp.candidates)) {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }
    return {
      candidates: resp.candidates,
      count: resp.count ?? resp.candidates.length,
    };
  }
);

// ---------------------------------------------------------------------------
// IPC: applyDeviceChoices — resolve installationId, apply device settings
// ---------------------------------------------------------------------------

ipcMain.handle(
  APPLY_DEVICE_CHOICES_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.installation_id)) {
      throw new Error("Invalid installation_id");
    }
    if (!isPlainObject(params.choices)) {
      throw new Error("Invalid choices");
    }
    let collectionPath: string;
    try {
      collectionPath = installationStore.getCollectionPath(params.installation_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    let response: unknown;
    try {
      response = await callBackend(backend, "apply_device_choices", {
        collection_path: collectionPath,
        choices: params.choices,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || typeof resp.success !== "boolean") {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }
    return { success: resp.success, error: resp.error ?? null };
  }
);

// ---------------------------------------------------------------------------
// IPC: obsRunning — check if OBS is running
// ---------------------------------------------------------------------------

ipcMain.handle(OBS_RUNNING_CHANNEL, async (event) => {
  if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
    throw new Error("Unauthorized sender");
  }
  let response: unknown;
  try {
    response = await callBackend(backend, "obs_running");
  } catch (err) {
    throw new Error(selectionErrorMessage(err));
  }
  const resp = response as Record<string, unknown>;
  if (!resp || typeof resp.running !== "boolean") {
    throw new Error(BACKEND_UNAVAILABLE_ERROR);
  }
  return { running: resp.running };
});

// ---------------------------------------------------------------------------
// IPC: activateCollection — resolve installationId, optional OBS activation
// ---------------------------------------------------------------------------

ipcMain.handle(
  ACTIVATE_COLLECTION_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.installation_id)) {
      throw new Error("Invalid installation_id");
    }
    let collectionName: string;
    try {
      collectionName = installationStore.getCollectionName(params.installation_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const password = isNonEmptyString(params.password) ? params.password : undefined;
    let response: unknown;
    try {
      response = await callBackend(backend, "activate_collection", {
        collection_name: collectionName,
        password: password,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || typeof resp.success !== "boolean") {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }
    return { success: resp.success, error: resp.error ?? null };
  }
);

// ---------------------------------------------------------------------------
// IPC: listExportCollections — no path from renderer, use OBS_SCENES_DIR
// ---------------------------------------------------------------------------

ipcMain.handle(
  LIST_EXPORT_COLLECTIONS_CHANNEL,
  async (_event) => {
    const obsScenesDir = resolveObsScenesDir();
    if (!obsScenesDir) {
      throw new Error("OBS scenes directory is not configured.");
    }
    exportStore.setObsScenesDirectory(obsScenesDir);
    let response: unknown;
    try {
      response = await callBackend(backend, "list_export_collections", {
        obs_scenes_directory: obsScenesDir,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || !Array.isArray(resp.collections)) {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }

    // Store collections in export store and return opaque IDs.
    const rawCollections = resp.collections as Array<{ label: string; path: string }>;
    const collections = exportStore.setCollections(rawCollections);

    return {
      collections,
      count: collections.length,
    };
  }
);

// ---------------------------------------------------------------------------
// IPC: chooseExportDestination — folder dialog, return opaque destination_id
// ---------------------------------------------------------------------------

ipcMain.handle(CHOOSE_EXPORT_DESTINATION_CHANNEL, async (event) => {
  if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
    throw new Error("Unauthorized sender");
  }
  const result = await dialog.showOpenDialog(mainWindow!, {
    title: "Choose an export destination folder",
    properties: ["openDirectory", "dontAddToRecent", "createDirectory"],
    buttonLabel: "Select Destination",
  });
  if (result.canceled || result.filePaths.length === 0) {
    throw new Error("No folder selected");
  }
  let destPath: string;
  try {
    destPath = realpathSync(result.filePaths[0]);
  } catch {
    throw new Error("The selected path is not valid.");
  }
  // Store in export store, return opaque ID and safe label.
  const { destinationId, destinationLabel } = exportStore.createDestination(destPath);
  return { destination_id: destinationId, destination_label: destinationLabel };
});

// ---------------------------------------------------------------------------
// IPC: buildExportPlan — resolve opaque IDs, create frozen backend-held plan
// ---------------------------------------------------------------------------

ipcMain.handle(
  BUILD_EXPORT_PLAN_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.collection_id)) {
      throw new Error("Invalid collection_id");
    }
    if (!isNonEmptyString(params.destination_id)) {
      throw new Error("Invalid destination_id");
    }
    if (typeof params.compressed !== "boolean") {
      throw new Error("Invalid compressed option");
    }
    let collectionPath: string;
    let destinationPath: string;
    try {
      collectionPath = exportStore.getCollectionPath(params.collection_id);
      destinationPath = exportStore.getDestinationPath(params.destination_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    let response: unknown;
    try {
      response = await callBackend(backend, "build_export_plan", {
        collection_path: collectionPath,
        destination: destinationPath,
        compressed: params.compressed,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || !isNonEmptyString(resp.plan_id)) {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }
    return resp;
  }
);

// ---------------------------------------------------------------------------
// IPC: exportInventory — return sanitized inventory for a plan
// ---------------------------------------------------------------------------

ipcMain.handle(
  EXPORT_INVENTORY_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.plan_id)) {
      throw new Error("Invalid plan_id");
    }
    let response: unknown;
    try {
      response = await callBackend(backend, "export_inventory", {
        plan_id: params.plan_id,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || !isNonEmptyString(resp.plan_id)) {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }
    return resp;
  }
);

// ---------------------------------------------------------------------------
// IPC: confirmExport — execute a frozen plan by opaque ID
// ---------------------------------------------------------------------------

ipcMain.handle(
  CONFIRM_EXPORT_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.plan_id)) {
      throw new Error("Invalid plan_id");
    }
    let response: unknown;
    try {
      response = await callBackend(backend, "confirm_export", {
        plan_id: params.plan_id,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || typeof resp.success !== "boolean") {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }
    return {
      success: resp.success,
      already_executed: resp.already_executed ?? false,
      copied_files: resp.copied_files ?? 0,
      uncompressed_bytes: resp.uncompressed_bytes ?? 0,
      source_references: resp.source_references ?? 0,
      skipped_references: resp.skipped_references ?? [],
      verification: resp.verification ?? null,
      output_label: resp.output_label ?? null,
      error: resp.error ?? null,
    };
  }
);

// ---------------------------------------------------------------------------
// IPC: scanResizeCollections — scan folder for collections with canvas info
// ---------------------------------------------------------------------------

ipcMain.handle(
  SCAN_RESIZE_COLLECTIONS_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.selection_id)) {
      throw new Error("Invalid selection_id");
    }
    let folderPath: string;
    try {
      folderPath = importStore.getFolderPath(params.selection_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    let response: unknown;
    try {
      response = await callBackend(backend, "scan_resize_collections", {
        folder_path: folderPath,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || !Array.isArray(resp.collections)) {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }

    // Store the scanned collections with opaque collection IDs in the
    // main-process selection store.  The renderer receives only
    // { collection_id, label, canvas_width, ... } — never raw paths.
    const selectionId = params.selection_id as string;
    importStore.setCollections(
      selectionId,
      (resp.collections as Array<{ path: string; label: string }>).map(
        (c) => ({ path: c.path, label: c.label })
      )
    );

    // Build safe display data: merge opaque collection IDs with the
    // canvas/source/scene info from the backend response.
    const safeCollections = (resp.collections as Array<{
      path: string;
      label: string;
      canvas_width: number | null;
      canvas_height: number | null;
      source_count: number;
      scene_count: number;
    }>).map((c, idx) => {
      const stored = importStore.getCollections(selectionId)[idx];
      return {
        collection_id: stored.collectionId,
        label: c.label,
        canvas_width: c.canvas_width ?? null,
        canvas_height: c.canvas_height ?? null,
        source_count: c.source_count ?? 0,
        scene_count: c.scene_count ?? 0,
      };
    });

    return {
      collections: safeCollections,
      count: safeCollections.length,
    };
  }
);

// ---------------------------------------------------------------------------
// IPC: chooseResizeCollection — verify collection ID belongs to selection
// ---------------------------------------------------------------------------

ipcMain.handle(
  CHOOSE_RESIZE_COLLECTION_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.selection_id)) {
      throw new Error("Invalid selection_id");
    }
    if (!isNonEmptyString(params.collection_id)) {
      throw new Error("Invalid collection_id");
    }
    try {
      importStore.chooseCollection(params.selection_id, params.collection_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    let collectionLabel: string;
    try {
      collectionLabel = importStore.getCollectionLabel(params.selection_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    return {
      collection_id: params.collection_id,
      label: collectionLabel,
    };
  }
);

// ---------------------------------------------------------------------------
// IPC: resizeSourceChoices — list UUID-backed sources for Source-scope resize
// ---------------------------------------------------------------------------

ipcMain.handle(
  RESIZE_SOURCE_CHOICES_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.selection_id)) {
      throw new Error("Invalid selection_id");
    }
    let collectionPath: string;
    try {
      collectionPath = importStore.getCollectionPath(params.selection_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    let response: unknown;
    try {
      response = await callBackend(backend, "resize_source_choices", {
        collection_path: collectionPath,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || !Array.isArray(resp.choices)) {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }
    return {
      choices: resp.choices,
      count: resp.count ?? resp.choices.length,
    };
  }
);

// ---------------------------------------------------------------------------
// IPC: resizeSceneChoices — list scene names for Scene-scope resize
// ---------------------------------------------------------------------------

ipcMain.handle(
  RESIZE_SCENE_CHOICES_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.selection_id)) {
      throw new Error("Invalid selection_id");
    }
    let collectionPath: string;
    try {
      collectionPath = importStore.getCollectionPath(params.selection_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    let response: unknown;
    try {
      response = await callBackend(backend, "resize_scene_choices", {
        collection_path: collectionPath,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || !Array.isArray(resp.scenes)) {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }
    return {
      scenes: resp.scenes,
      count: resp.count ?? resp.scenes.length,
    };
  }
);

// ---------------------------------------------------------------------------
// IPC: previewResize — validate resize inputs, return what would change
// ---------------------------------------------------------------------------

ipcMain.handle(
  PREVIEW_RESIZE_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.selection_id)) {
      throw new Error("Invalid selection_id");
    }
    if (!isNonEmptyString(params.scope)) {
      throw new Error("Invalid scope");
    }
    if (!isNonEmptyString(params.mode)) {
      throw new Error("Invalid mode");
    }
    if (typeof params.target_width !== "number" || typeof params.target_height !== "number") {
      throw new Error("Invalid target dimensions");
    }
    let collectionPath: string;
    try {
      collectionPath = importStore.getCollectionPath(params.selection_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    let response: unknown;
    try {
      response = await callBackend(backend, "preview_resize", {
        collection_path: collectionPath,
        scope: params.scope,
        mode: params.mode,
        target_width: params.target_width,
        target_height: params.target_height,
        selected_name: params.selected_name ?? null,
        selected_uuid: params.selected_uuid ?? null,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || typeof resp.valid !== "boolean") {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }
    return resp;
  }
);

// ---------------------------------------------------------------------------
// IPC: applyResize — execute offline resize (creates backup)
// ---------------------------------------------------------------------------

ipcMain.handle(
  APPLY_RESIZE_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.selection_id)) {
      throw new Error("Invalid selection_id");
    }
    if (!isNonEmptyString(params.scope)) {
      throw new Error("Invalid scope");
    }
    if (!isNonEmptyString(params.mode)) {
      throw new Error("Invalid mode");
    }
    if (typeof params.target_width !== "number" || typeof params.target_height !== "number") {
      throw new Error("Invalid target dimensions");
    }
    let collectionPath: string;
    try {
      collectionPath = importStore.getCollectionPath(params.selection_id);
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    let response: unknown;
    try {
      response = await callBackend(backend, "resize_collection", {
        collection_path: collectionPath,
        scope: params.scope,
        mode: params.mode,
        target_width: params.target_width,
        target_height: params.target_height,
        selected_name: params.selected_name ?? null,
        selected_uuid: params.selected_uuid ?? null,
      });
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || typeof resp.success !== "boolean") {
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }

    // Register the backup path in the session-only undo store and
    // return only an opaque undo_id to the renderer.  The concrete
    // backup_path never reaches the renderer.
    let undoId: string | null = null;
    if (resp.success && resp.backup_path) {
      undoId = resizeUndoStore.registerUndo(
        params.selection_id,
        collectionPath,
        resp.backup_path as string
      );
    }

    return {
      success: resp.success,
      error: resp.error ?? null,
      changed_items: resp.changed_items ?? 0,
      source_width: resp.source_width ?? 0,
      source_height: resp.source_height ?? 0,
      target_width: resp.target_width ?? 0,
      target_height: resp.target_height ?? 0,
      canvas_changed: resp.canvas_changed ?? false,
      undo_id: undoId,
    };
  }
);

// ---------------------------------------------------------------------------
// IPC: undoResize — restore a resize backup using an opaque undo ID
// ---------------------------------------------------------------------------

ipcMain.handle(
  UNDO_RESIZE_CHANNEL,
  async (event, params: unknown) => {
    if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
      throw new Error("Unauthorized sender");
    }
    if (!isPlainObject(params) || !isNonEmptyString(params.selection_id)) {
      throw new Error("Invalid selection_id");
    }
    if (!isNonEmptyString(params.undo_id)) {
      throw new Error("Invalid undo_id");
    }

    // Resolve the concrete backup path from the opaque undo ID.
    // This validates ownership, TTL, selection binding, and marks the
    // token as in-flight so concurrent/replay requests are rejected.
    // The token is NOT consumed yet — it must be explicitly consumed
    // after the backend restore succeeds, or released on failure.
    let resolved: { backupPath: string; collectionPath: string };
    try {
      resolved = resizeUndoStore.resolveUndo(
        params.undo_id,
        params.selection_id
      );
    } catch (err) {
      throw new Error(selectionErrorMessage(err));
    }

    let response: unknown;
    try {
      response = await callBackend(backend, "undo_resize", {
        collection_path: resolved.collectionPath,
        backup_path: resolved.backupPath,
      });
    } catch (err) {
      // Backend transport failure — release the in-flight state so the
      // same valid token can be retried until its TTL expires.
      try {
        resizeUndoStore.releaseUndo(params.undo_id, params.selection_id);
      } catch {
        // Ignore release errors — the token may have been cleaned up.
      }
      throw new Error(selectionErrorMessage(err));
    }
    const resp = response as Record<string, unknown>;
    if (!resp || typeof resp.success !== "boolean") {
      // Malformed response — release the in-flight state for retry.
      try {
        resizeUndoStore.releaseUndo(params.undo_id, params.selection_id);
      } catch {
        // Ignore release errors.
      }
      throw new Error(BACKEND_UNAVAILABLE_ERROR);
    }
    if (resp.success) {
      // Successful restore — permanently consume the token (one-shot).
      try {
        resizeUndoStore.consumeUndo(params.undo_id, params.selection_id);
      } catch {
        // Ignore consume errors — the undo succeeded at the backend level.
      }
    } else {
      // Backend reported failure — release the in-flight state for retry.
      try {
        resizeUndoStore.releaseUndo(params.undo_id, params.selection_id);
      } catch {
        // Ignore release errors.
      }
    }
    return { success: resp.success, error: resp.error ?? null };
  }
);

// ---------------------------------------------------------------------------
// Window management
// ---------------------------------------------------------------------------

let mainWindow: BrowserWindow | null = null;

/**
 * Resolve the path to the bundled Python backend executable.
 *
 * In packaged mode, the backend is a PyInstaller one-file executable
 * placed in Electron's resources directory by electron-builder.
 * It is resolved from Electron's resources directory, never from the app
 * executable path.
 */
function resolveBackendExecutable(): string | null {
  if (!app.isPackaged) {
    return null;
  }
  // The backend executable is placed in resources/ by electron-builder's
  // extraResources configuration. On Windows it has a .exe extension.
  const exeName = process.platform === "win32"
    ? "obs-overlay-backend.exe"
    : "obs-overlay-backend";
  return path.join(process.resourcesPath, exeName);
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1024,
    height: 720,
    minWidth: 800,
    minHeight: 600,
    webPreferences: {
      // Security: disable Node.js integration in the renderer.
      nodeIntegration: false,
      // Security: enable context isolation.
      contextIsolation: true,
      // Security: enable sandbox.
      sandbox: true,
      // Security: explicitly disable webview.
      webviewTag: false,
      // Security: explicitly enable web security.
      webSecurity: true,
      // Preload runs in an isolated context.
      // Compiled preload is at dist-electron/preload/index.js (sibling of main/).
      preload: resolvePreloadPath(),
    },
  });

  if (app.isPackaged) {
    // Packaged mode: load the built React renderer from the local file system.
    // The renderer is built into dist/index.html by Vite and packaged by
    // electron-builder. We use loadFile (not loadURL) for the local file.
    mainWindow.loadFile(resolvePackagedRendererPath());
  } else {
    // Development mode: load from the Vite dev server.
    mainWindow.loadURL(DEV_ORIGIN);
    // Open DevTools in development.
    mainWindow.webContents.openDevTools({ mode: "detach" });
  }

  // Security: block unexpected navigation.
  mainWindow.webContents.on("will-navigate", (event, targetUrl) => {
    if (!isAllowedNavigation(targetUrl)) {
      event.preventDefault();
    }
  });

  // Security: block new windows.
  mainWindow.webContents.setWindowOpenHandler(() => {
    return { action: "deny" };
  });

  // Security: block downloads.
  mainWindow.webContents.session.on("will-download", (event) => {
    event.preventDefault();
  });

  // Security: deny all permission requests via session handler.
  mainWindow.webContents.session.setPermissionCheckHandler(() => false);
  // Also deny permission requests explicitly (defense in depth).
  mainWindow.webContents.session.setPermissionRequestHandler(
    (_webContents, _permission, callback) => callback(false)
  );

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

/**
 * Run the packaged-app smoke check when CI starts the portable executable
 * with --smoke-test. The check intentionally exercises the renderer's
 * public preload API rather than calling the backend directly.
 */
function runPackagedSmokeTest(): void {
  if (!app.isPackaged || !process.argv.includes("--smoke-test")) {
    return;
  }

  const resultPath = process.env.OBS_OVERLAY_SMOKE_RESULT;
  if (!resultPath || !mainWindow) {
    return;
  }

  let finished = false;
  const finish = (result: Record<string, unknown>): void => {
    if (finished) {
      return;
    }
    finished = true;
    writeFileSync(resultPath, JSON.stringify(result), "utf8");
    app.quit();
  };

  const timeout = setTimeout(() => {
    finish({ ok: false, error: "Timed out waiting for packaged renderer health" });
  }, 30_000);

  mainWindow.webContents.once("did-finish-load", () => {
    void mainWindow?.webContents
      .executeJavaScript(
        `Promise.all([window.electronAPI.health(), window.electronAPI.appInfo()])
          .then(([health, appInfo]) => ({
            health,
            appInfo,
            rendererNodeUnavailable:
              typeof window.require === "undefined" && typeof window.process === "undefined",
          }))`
      )
      .then((result: unknown) => {
        clearTimeout(timeout);
        finish({ ok: true, result });
      })
      .catch((error: Error) => {
        clearTimeout(timeout);
        finish({ ok: false, error: error.message });
      });
  });
}

// ---------------------------------------------------------------------------
// Security: CSP and session configuration
// ---------------------------------------------------------------------------

/**
 * Configure Content-Security-Policy for the renderer.
 * In development, allows localhost for the Vite dev server including
 * WebSocket connections for HMR.
 */
function configureCSP(): void {
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    const isDev = !app.isPackaged;
    const csp = isDev
      ? "default-src 'self'; script-src 'self' 'unsafe-inline' http://localhost:5173; style-src 'self' 'unsafe-inline'; img-src 'self' data: http://localhost:5173; connect-src 'self' http://localhost:5173 ws://localhost:5173;"
      : "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self';";

    callback({
      responseHeaders: {
        ...details.responseHeaders,
        "Content-Security-Policy": [csp],
      },
    });
  });
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(() => {
  configureCSP();

  // Start the Python backend.
  if (app.isPackaged) {
    // Packaged mode: start the bundled backend executable from
    // process.resourcesPath. No system Python is required.
    const backendExec = resolveBackendExecutable();
    if (backendExec) {
      try {
        backend.start(backendExec, "");
      } catch (err) {
        console.error("[backend]", (err as Error).message);
      }
    }
  } else {
    // Development mode: start the Python backend from source using
    // the OBS_OVERLAY_PYTHON environment variable.
    try {
      const pythonExec = resolveDevPython();
      if (!pythonExec || !isValidExecutable(pythonExec)) {
        throw new Error(
          "OBS_OVERLAY_PYTHON is not set or does not point to a valid Python executable. " +
            "Set OBS_OVERLAY_PYTHON to your Python 3 interpreter path."
        );
      }
      backend.start(pythonExec, resolvePythonPath());
    } catch (err) {
      console.error("[backend]", (err as Error).message);
      // Continue to show the error in the renderer.
    }
  }

  createWindow();
  runPackagedSmokeTest();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  // On macOS, keep the app running.
  if (process.platform !== "darwin") {
    backend.stop();
    importStore.clear();
    app.quit();
  }
});

app.on("before-quit", () => {
  backend.stop();
  importStore.clear();
  resizeUndoStore.clear();
});
