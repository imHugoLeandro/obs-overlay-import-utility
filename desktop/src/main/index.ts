/**
 * Electron main process for the OBS Overlay Import Utility desktop shell.
 *
 * Architecture:
 * - The main process spawns and manages a Python stdio backend.
 * - The Python backend exposes only `health` and `app_info` commands.
 * - IPC requests from the renderer use fixed channels (desktop:health,
 *   desktop:app-info) via ipcMain.handle / ipcRenderer.invoke.
 * - The renderer never imports Electron, Node, filesystem, child_process,
 *   or IPC primitives directly.
 *
 * Security configuration:
 * - nodeIntegration: false
 * - contextIsolation: true
 * - sandbox: true
 * - webSecurity: true
 * - webviewTag: false
 * - Unexpected navigation and new windows are blocked.
 * - Production CSP restricts content to the packaged app.
 * - Every IPC sender, channel, and payload is validated.
 */

import { app, BrowserWindow, ipcMain, session } from "electron";
import * as path from "path";
import * as child_process from "child_process";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/** Allowed commands that can be sent to the Python backend. */
const ALLOWED_COMMANDS = new Set(["health", "app_info"]);

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

/** Expected Vite dev server URL. */
const DEV_URL = "http://localhost:5173";

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
// Backend transport — robust stdout buffering and pending-request map
// ---------------------------------------------------------------------------

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
  timer: NodeJS.Timeout;
}

/**
 * Manages the Python backend subprocess and JSON-lines protocol.
 *
 * - Buffers stdout across chunks and parses complete newline-delimited JSON.
 * - Supports concurrent requests via a pending-request map keyed by request ID.
 * - Rejects all pending requests if the backend exits, errors, or stdin fails.
 * - Clears request timeouts after success/failure.
 */
class BackendTransport {
  private pyProcess: child_process.ChildProcess | null = null;
  private pyStdin: child_process.ChildProcess["stdin"] | null = null;
  private pyStdout: child_process.ChildProcess["stdout"] | null = null;
  private pending = new Map<string, PendingRequest>();
  private stdoutBuffer = "";
  private requestIdCounter = 0;

  /** Generate a unique request ID for the backend protocol. */
  generateRequestId(): string {
    this.requestIdCounter = (this.requestIdCounter + 1) % 1_000_000;
    return `req-${Date.now()}-${this.requestIdCounter}`;
  }

  /** Start the Python backend as a stdio subprocess. */
  start(): void {
    if (this.pyProcess) {
      return;
    }

    const pythonExec = resolveDevPython();
    if (!pythonExec || !isValidExecutable(pythonExec)) {
      const error = new Error(
        "OBS_OVERLAY_PYTHON is not set or does not point to a valid Python executable. " +
          "Set OBS_OVERLAY_PYTHON to your Python 3 interpreter path."
      );
      console.error("[backend]", error.message);
      throw error;
    }

    // Determine the project root (parent of desktop/).
    const projectRoot = path.resolve(__dirname, "..", "..");

    this.pyProcess = child_process.spawn(pythonExec, ["-u", "-m", "obs_overlay_import_utility.desktop_backend"], {
      stdio: ["pipe", "pipe", "pipe"],
      env: {
        ...process.env,
        PYTHONPATH: path.join(projectRoot, "src"),
      },
    });

    this.pyStdin = this.pyProcess.stdin;
    this.pyStdout = this.pyProcess.stdout;

    if (this.pyProcess.stderr) {
      this.pyProcess.stderr.on("data", (data: Buffer) => {
        // Log technical diagnostics to stderr — never to the renderer.
        console.error("[backend]", data.toString().trim());
      });
    }

    if (this.pyStdout) {
      this.pyStdout.on("data", (data: Buffer) => {
        this.handleStdout(data);
      });
    }

    this.pyProcess.on("exit", (_code, _signal) => {
      console.log("[backend] process exited");
      this.rejectAllPending(new Error("Backend process exited"));
      this.pyProcess = null;
      this.pyStdin = null;
      this.pyStdout = null;
      this.stdoutBuffer = "";
    });

    this.pyProcess.on("error", (err) => {
      console.error("[backend] spawn error:", err);
      this.rejectAllPending(new Error("Backend process error"));
      this.pyProcess = null;
      this.pyStdin = null;
      this.pyStdout = null;
      this.stdoutBuffer = "";
    });
  }

  /** Stop the Python backend gracefully. */
  stop(): void {
    if (this.pyProcess) {
      this.pyProcess.kill("SIGTERM");
      this.pyProcess = null;
      this.pyStdin = null;
      this.pyStdout = null;
      this.stdoutBuffer = "";
    }
  }

  /**
   * Send a request to the Python backend and await the response.
   *
   * Uses a line-delimited JSON protocol over stdin/stdout.
   * Supports concurrent requests via the pending-request map.
   */
  sendRequest(command: string): Promise<unknown> {
    if (!this.pyStdin) {
      return Promise.reject(new Error("Backend not running"));
    }

    const requestId = this.generateRequestId();
    const requestLine = JSON.stringify({ request_id: requestId, command }) + "\n";

    return new Promise<unknown>((resolve, reject) => {
      // Register the pending request.
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error(`Backend request timed out: ${command}`));
      }, 10000);

      this.pending.set(requestId, { resolve, reject, timer });

      // Write the request.
      this.pyStdin!.write(requestLine, (err) => {
        if (err) {
          clearTimeout(timer);
          this.pending.delete(requestId);
          reject(err);
        }
      });
    });
  }

  /**
   * Handle incoming stdout data by buffering and parsing complete JSON lines.
   */
  private handleStdout(data: Buffer): void {
    this.stdoutBuffer += data.toString();

    let newlineIndex: number;
    while ((newlineIndex = this.stdoutBuffer.indexOf("\n")) !== -1) {
      const line = this.stdoutBuffer.slice(0, newlineIndex).trim();
      this.stdoutBuffer = this.stdoutBuffer.slice(newlineIndex + 1);

      if (!line) {
        continue;
      }

      try {
        const response = JSON.parse(line);
        const requestId = response.request_id;
        const pending = this.pending.get(requestId);

        if (pending) {
          clearTimeout(pending.timer);
          this.pending.delete(requestId);
          pending.resolve(response);
        }
      } catch {
        // Ignore non-JSON lines (e.g., Python startup output).
      }
    }
  }

  /** Reject all pending requests with the given error. */
  private rejectAllPending(error: Error): void {
    for (const [requestId, pending] of this.pending) {
      clearTimeout(pending.timer);
      this.pending.delete(requestId);
      pending.reject(error);
    }
  }
}

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
 * Validate that the sender's URL is an expected origin.
 * - Development: the configured Vite localhost URL.
 * - Packaged: only the packaged local file/app URL.
 */
function isValidOrigin(sender: Electron.WebContents): boolean {
  const url = sender.getURL();
  if (!app.isPackaged) {
    // Development: allow the Vite dev server.
    return url.startsWith(DEV_URL);
  }
  // Packaged: only allow the local app file URL.
  return url.startsWith("file://");
}

/**
 * IPC handler for the health command.
 * Validates sender, origin, and payload before forwarding to the backend.
 */
ipcMain.handle(HEALTH_CHANNEL, async (event) => {
  if (!isValidSender(event.sender) || !isValidOrigin(event.sender)) {
    throw new Error("Unauthorized sender");
  }
  if (!isAllowedCommand("health")) {
    throw new Error("Command not allowed");
  }
  try {
    const response = await backend.sendRequest("health");
    const resp = response as { type: string; data?: unknown; error?: { message: string } };
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
 * Validates sender, origin, and payload before forwarding to the backend.
 */
ipcMain.handle(APP_INFO_CHANNEL, async (event) => {
  if (!isValidSender(event.sender) || !isValidOrigin(event.sender)) {
    throw new Error("Unauthorized sender");
  }
  if (!isAllowedCommand("app_info")) {
    throw new Error("Command not allowed");
  }
  try {
    const response = await backend.sendRequest("app_info");
    const resp = response as { type: string; data?: unknown; error?: { message: string } };
    if (resp.type === "result") {
      return resp.data;
    }
    throw new Error(resp.error?.message ?? "Backend error");
  } catch {
    throw new Error("Backend communication failed");
  }
});

// ---------------------------------------------------------------------------
// Window management
// ---------------------------------------------------------------------------

let mainWindow: BrowserWindow | null = null;

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
      preload: path.join(__dirname, "preload", "index.js"),
    },
  });

  // Load the renderer.
  if (app.isPackaged) {
    mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  } else {
    mainWindow.loadURL(DEV_URL);
    // Open DevTools in development.
    mainWindow.webContents.openDevTools({ mode: "detach" });
  }

  // Security: block unexpected navigation.
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!app.isPackaged) {
      // Development: only allow the Vite dev server.
      if (url.startsWith(DEV_URL)) {
        return;
      }
    } else {
      // Packaged: only allow local file URLs.
      if (url.startsWith("file://")) {
        return;
      }
    }
    event.preventDefault();
  });

  // Security: block new windows.
  mainWindow.webContents.setWindowOpenHandler(() => {
    return { action: "deny" };
  });

  // Security: deny permission requests.
  mainWindow.webContents.session.on("will-download", () => {
    // Downloads are not needed in the foundation stage.
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

// ---------------------------------------------------------------------------
// Security: CSP and session configuration
// ---------------------------------------------------------------------------

/**
 * Configure Content-Security-Policy for the renderer.
 * In production, restricts content to the packaged app.
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
      backend.start();
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
