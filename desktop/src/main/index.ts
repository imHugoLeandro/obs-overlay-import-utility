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
 * - Selected absolute paths are held in the main process (for the folder
 *   dialog) and forwarded to the Python backend, which stores them in an
 *   in-memory, session-only selection store.  The renderer receives only
 *   opaque selection IDs and safe display labels.
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
import {
  DEV_ORIGIN,
  isValidOrigin,
  isAllowedNavigation,
  resolvePythonPath,
  resolvePreloadPath,
} from "./security";
import { BackendTransport } from "./transport";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/** Allowed commands that can be sent to the Python backend. */
const ALLOWED_COMMANDS = new Set([
  "health",
  "app_info",
  "choose_folder",
  "scan_collections",
  "choose_collection",
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
const CHOOSE_FOLDER_CHANNEL = "desktop:choose-folder";
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
    const fs = require("fs");
    return fs.existsSync(filePath) && fs.statSync(filePath).isFile();
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Backend transport
// ---------------------------------------------------------------------------

const backend = new BackendTransport();

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
 * IPC handler for the health command.
 * Validates sender, origin, and command before forwarding to the backend.
 */
ipcMain.handle(HEALTH_CHANNEL, async (event) => {
  if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
    throw new Error("Unauthorized sender");
  }
  if (!isAllowedCommand("health")) {
    throw new Error("Command not allowed");
  }
  try {
    const response = await backend.sendRequest("health");
    const resp = response as {
      type: string;
      data?: unknown;
      error?: { message: string };
    };
    if (resp.type === "result") {
      return resp.data;
    }
    throw new Error(resp.error?.message ?? "Backend error");
  } catch {
    throw new Error("Backend communication failed");
  }
});

/**
 * IPC handler for the app_info command.
 * Validates sender, origin, and command before forwarding to the backend.
 */
ipcMain.handle(APP_INFO_CHANNEL, async (event) => {
  if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
    throw new Error("Unauthorized sender");
  }
  if (!isAllowedCommand("app_info")) {
    throw new Error("Command not allowed");
  }
  try {
    const response = await backend.sendRequest("app_info");
    const resp = response as {
      type: string;
      data?: unknown;
      error?: { message: string };
    };
    if (resp.type === "result") {
      return resp.data;
    }
    throw new Error(resp.error?.message ?? "Backend error");
  } catch {
    throw new Error("Backend communication failed");
  }
});

/**
 * IPC handler for the choose_folder command.
 *
 * Opens a folder dialog, validates the selected path, and forwards it to
 * the Python backend's `choose_folder` command.  The backend stores the
 * absolute path in its in-memory selection store and returns an opaque
 * selection ID plus a safe label.  The raw absolute path never reaches
 * the renderer.
 */
ipcMain.handle(CHOOSE_FOLDER_CHANNEL, async (event) => {
  if (!isValidSender(event.sender) || !isValidOrigin(event.sender.getURL())) {
    throw new Error("Unauthorized sender");
  }
  if (!isAllowedCommand("choose_folder")) {
    throw new Error("Command not allowed");
  }

  // Open a folder dialog — the main process holds the absolute path.
  const result = await dialog.showOpenDialog(mainWindow!, {
    title: "Choose an extracted overlay folder",
    properties: ["openDirectory", "dontAddToRecent", "createDirectory"],
    buttonLabel: "Select Overlay Folder",
  });

  if (result.canceled || result.filePaths.length === 0) {
    throw new Error("No folder selected");
  }

  const folderPath = result.filePaths[0];

  try {
    const response = await backend.sendRequest("choose_folder", {
      folder_path: folderPath,
    });
    const resp = response as {
      type: string;
      data?: unknown;
      error?: { message: string };
    };
    if (resp.type === "result") {
      return resp.data;
    }
    throw new Error(resp.error?.message ?? "Backend error");
  } catch {
    throw new Error("Backend communication failed");
  }
});

/**
 * IPC handler for the scan_collections command.
 * Validates the selection ID payload before forwarding to the backend.
 */
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
  try {
    const response = await backend.sendRequest("scan_collections", {
      selection_id: params.selection_id,
    });
    const resp = response as {
      type: string;
      data?: unknown;
      error?: { message: string };
    };
    if (resp.type === "result") {
      return resp.data;
    }
    throw new Error(resp.error?.message ?? "Backend error");
  } catch {
    throw new Error("Backend communication failed");
  }
});

/**
 * IPC handler for the choose_collection command.
 * Validates the selection ID and collection index before forwarding.
 */
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
    if (
      typeof params.collection_index !== "number" ||
      !Number.isInteger(params.collection_index) ||
      params.collection_index < 0
    ) {
      throw new Error("Invalid collection_index");
    }
    try {
      const response = await backend.sendRequest("choose_collection", {
        selection_id: params.selection_id,
        collection_index: params.collection_index,
      });
      const resp = response as {
        type: string;
        data?: unknown;
        error?: { message: string };
      };
      if (resp.type === "result") {
        return resp.data;
      }
      throw new Error(resp.error?.message ?? "Backend error");
    } catch {
      throw new Error("Backend communication failed");
    }
  }
);

/**
 * IPC handler for the convert_collection command.
 * Validates the selection ID and boolean options before forwarding.
 */
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
    try {
      const response = await backend.sendRequest("convert_collection", {
        selection_id: params.selection_id,
        strict: params.strict,
        case_sensitive: params.case_sensitive,
      });
      const resp = response as {
        type: string;
        data?: unknown;
        error?: { message: string };
      };
      if (resp.type === "result") {
        return resp.data;
      }
      throw new Error(resp.error?.message ?? "Backend error");
    } catch {
      throw new Error("Backend communication failed");
    }
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
    app.quit();
  }
});

app.on("before-quit", () => {
  backend.stop();
});
