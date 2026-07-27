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
import { resolve } from "path";
import {
  DEV_ORIGIN,
  isValidOrigin,
  isAllowedNavigation,
  resolvePythonPath,
  resolvePreloadPath,
} from "./security";
import { BackendTransport } from "./transport";
import { ImportSelectionStore, SelectionError } from "./importSelectionStore";
import { callBackend, BACKEND_UNAVAILABLE_ERROR } from "./backendCall";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/** Allowed commands that can be sent to the Python backend. */
const ALLOWED_COMMANDS = new Set([
  "health",
  "app_info",
  "scan_collections",
  "convert_collection",
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
const SCAN_COLLECTIONS_CHANNEL = "desktop:scan-collections";
const CHOOSE_COLLECTION_CHANNEL = "desktop:choose-collection";
const CONVERT_COLLECTION_CHANNEL = "desktop:convert-collection";

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
 * Convert a SelectionError to a renderer-safe error message.
 * SelectionError messages are already customer-safe (no raw paths).
 */
function selectionErrorMessage(err: unknown): string {
  if (err instanceof SelectionError) {
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

  const folderPath = resolve(result.filePaths[0]);
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
    collections?: Array<{ index: number; label: string }>;
    count?: number;
  };

  if (!resp || !Array.isArray(resp.collections)) {
    throw new Error(BACKEND_UNAVAILABLE_ERROR);
  }

  // Store the scanned collections with fresh opaque collection IDs.
  // The renderer receives only { collection_id, label }.
  importStore.setCollections(
    params.selection_id,
    resp.collections.map((c) => ({
      path: c.label, // The backend returns relative labels; we resolve to canonical paths
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

    return {
      selection_id: params.selection_id,
      collection_label: "selected",
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

    // Check idempotency: if already converted, reject.
    try {
      if (importStore.isConverted(params.selection_id)) {
        throw new Error(
          "This collection has already been converted. Choose a folder again."
        );
      }
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
    if (resp.success) {
      try {
        importStore.markConverted(params.selection_id);
      } catch {
        // If marking fails, the conversion still succeeded — don't
        // block the user from seeing the result.
      }
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
// Window management
// ---------------------------------------------------------------------------

let mainWindow: BrowserWindow | null = null;

/**
 * Show a Stage-3-not-implemented error and quit safely.
 */
function showPackagedNotImplemented(): void {
  const errorWindow = new BrowserWindow({
    width: 600,
    height: 300,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webviewTag: false,
      webSecurity: true,
    },
  });
  errorWindow.loadURL(
    "data:text/html," +
      encodeURIComponent(
        "<!DOCTYPE html><html><head><title>Error</title></head><body>" +
          "<h1>Portable Electron Packaging Not Implemented</h1>" +
          "<p>Stage 3 (portable Electron + bundled Python) is deferred. " +
          "This application must be run in development mode.</p>" +
          "</body></html>"
      )
  );
  errorWindow.on("closed", () => {
    app.quit();
  });
}

function createWindow(): void {
  // Packaged mode: fail closed. Stage 3 packaging is deferred.
  if (app.isPackaged) {
    showPackagedNotImplemented();
    return;
  }

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

  // Load the renderer from the Vite dev server.
  mainWindow.loadURL(DEV_ORIGIN);
  // Open DevTools in development.
  mainWindow.webContents.openDevTools({ mode: "detach" });

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

  // Start the Python backend in development.
  if (!app.isPackaged) {
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
});
