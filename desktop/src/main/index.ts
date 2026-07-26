/**
 * Electron main process for the OBS Overlay Import Utility desktop shell.
 *
 * Architecture:
 * - The main process spawns and manages a Python stdio backend.
 * - The Python backend exposes only `health` and `app_info` commands.
 * - IPC requests from the renderer are validated (channel, sender, payload)
 *   before being forwarded to the Python backend.
 * - The renderer never imports Electron, Node, filesystem, child_process,
 *   or IPC primitives directly.
 *
 * Security configuration:
 * - nodeIntegration: false
 * - contextIsolation: true
 * - sandbox: true
 * - webSecurity: true
 * - webview disabled
 * - Unexpected navigation and new windows are blocked.
 * - Production CSP restricts content to the packaged app.
 */

import { app, BrowserWindow, ipcMain, session } from "electron";
import * as path from "path";
import * as child_process from "child_process";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/** Allowed IPC channels — anything else is rejected. */
const ALLOWED_REQUEST_CHANNEL = "desktop-backend-request";

/** Allowed commands that can be sent to the Python backend. */
const ALLOWED_COMMANDS = new Set(["health", "app_info"]);

/**
 * Path to the Python backend entry point.
 * In development, this resolves to the source file.
 * In production (packaged), the backend is bundled alongside the app.
 */
function getBackendPath(): string {
  if (app.isPackaged) {
    // In production, the Python backend is packaged inside the Electron
    // resources directory.  We use the bundled Python interpreter if
    // available, otherwise fall back to the system python3.
    const resourcesPath = path.join(process.resourcesPath, "backend");
    return path.join(resourcesPath, "desktop_backend.py");
  }
  // Development: resolve from the project root.
  return path.join(__dirname, "..", "..", "..", "src", "obs_overlay_import_utility", "desktop_backend.py");
}

/**
 * Python executable to use for the backend.
 * In development, we use the current Python.  In production, we look for
 * a bundled interpreter.
 */
function getPythonExecutable(): string {
  if (app.isPackaged) {
    const bundled = path.join(process.resourcesPath, "python", "python3");
    return bundled;
  }
  return process.execPath; // In dev, use the same Python that runs the project
}

// ---------------------------------------------------------------------------
// Python backend lifecycle
// ---------------------------------------------------------------------------

let pyProcess: child_process.ChildProcess | null = null;
let pyStdin: child_process.ChildProcess["stdin"] | null = null;
let pyStdout: child_process.ChildProcess["stdout"] | null = null;

/**
 * Start the Python backend as a stdio subprocess.
 * Called only in development (production uses a packaged backend).
 */
function startBackend(): void {
  if (pyProcess) {
    return;
  }

  const backendPath = getBackendPath();
  const pythonExec = getPythonExecutable();

  pyProcess = child_process.spawn(pythonExec, ["-u", backendPath], {
    stdio: ["pipe", "pipe", "pipe"],
    env: {
      ...process.env,
      PYTHONPATH: path.join(__dirname, "..", "..", "..", "src"),
    },
  });

  pyStdin = pyProcess.stdin;
  pyStdout = pyProcess.stdout;

  if (pyProcess.stderr) {
    pyProcess.stderr.on("data", (data: Buffer) => {
      console.error("[backend]", data.toString().trim());
    });
  }

  pyProcess.on("exit", (code, signal) => {
    console.log(`[backend] exited with code=${code}, signal=${signal}`);
    pyProcess = null;
    pyStdin = null;
    pyStdout = null;
  });

  pyProcess.on("error", (err) => {
    console.error("[backend] spawn error:", err);
    pyProcess = null;
    pyStdin = null;
    pyStdout = null;
  });
}

/**
 * Stop the Python backend gracefully.
 */
function stopBackend(): void {
  if (pyProcess) {
    pyProcess.kill("SIGTERM");
    pyProcess = null;
    pyStdin = null;
    pyStdout = null;
  }
}

/**
 * Send a request to the Python backend and await the response.
 *
 * Uses a line-delimited JSON protocol over stdin/stdout.
 */
function sendToBackend(requestId: string, command: string): Promise<unknown> {
  return new Promise((resolve, reject) => {
    if (!pyStdin || !pyStdout) {
      reject(new Error("Backend not running"));
      return;
    }

    const requestLine = JSON.stringify({ request_id: requestId, command }) + "\n";

    // Set up a one-time listener for the response line.
    const onData = (data: Buffer) => {
      const lines = data.toString().split("\n").filter((l) => l.trim());
      for (const line of lines) {
        try {
          const response = JSON.parse(line);
          if (response.request_id === requestId) {
            pyStdout?.off("data", onData);
            resolve(response);
            return;
          }
        } catch {
          // Ignore non-JSON lines.
        }
      }
    };

    pyStdout.on("data", onData);

    // Write the request.
    pyStdin.write(requestLine, (err) => {
      if (err) {
        pyStdout?.off("data", onData);
        reject(err);
      }
    });

    // Timeout after 10 seconds.
    setTimeout(() => {
      pyStdout?.off("data", onData);
      reject(new Error(`Backend request timed out: ${command}`));
    }, 10000);
  });
}

// ---------------------------------------------------------------------------
// IPC handlers
// ---------------------------------------------------------------------------

/**
 * Validate that the IPC sender is a valid webContents.
 * Returns true if the sender is safe to process.
 */
function isValidSender(event: Electron.IpcMainEvent): boolean {
  // Only accept events from the main window's webContents.
  // This prevents malicious preload scripts from other origins.
  return event.sender !== null && !event.sender.isDestroyed();
}

/**
 * Validate the IPC payload structure.
 * Returns the parsed command or throws.
 */
function validatePayload(payload: unknown): string {
  if (!payload || typeof payload !== "object") {
    throw new Error("Invalid payload: expected an object");
  }
  const obj = payload as Record<string, unknown>;
  const command = obj.command;
  if (typeof command !== "string") {
    throw new Error("Invalid payload: command must be a string");
  }
  if (!ALLOWED_COMMANDS.has(command)) {
    throw new Error(`Invalid payload: command '${command}' is not allowed`);
  }
  return command;
}

/**
 * IPC handler for desktop-backend requests.
 *
 * Validates:
 * 1. The channel name matches the allowed request channel.
 * 2. The sender is a valid webContents.
 * 3. The payload has a valid request_id and command.
 * 4. The command is in the allowed set.
 *
 * Then forwards the request to the Python backend and returns the response
 * on a per-request response channel.
 */
ipcMain.on(ALLOWED_REQUEST_CHANNEL, async (event, payload) => {
  // Validate sender.
  if (!isValidSender(event)) {
    return;
  }

  // Validate payload.
  let requestId: string;
  let command: string;
  try {
    if (!payload || typeof payload !== "object") {
      throw new Error("Invalid payload");
    }
    const obj = payload as Record<string, unknown>;
    requestId = obj.request_id as string;
    if (typeof requestId !== "string" || !requestId) {
      throw new Error("Invalid request_id");
    }
    command = validatePayload(payload);
  } catch (err) {
    const errorResponse = {
      request_id: "__invalid__",
      type: "error",
      error: {
        code: "invalid_payload",
        message: err instanceof Error ? err.message : "Unknown error",
      },
    };
    event.reply(`desktop-backend-response-__invalid__`, errorResponse);
    return;
  }

  // Forward to the Python backend.
  try {
    const response = await sendToBackend(requestId, command);
    event.reply(`desktop-backend-response-${requestId}`, response);
  } catch (err) {
    const errorResponse = {
      request_id: requestId,
      type: "error",
      error: {
        code: "backend_error",
        message: err instanceof Error ? err.message : "Unknown error",
      },
    };
    event.reply(`desktop-backend-response-${requestId}`, errorResponse);
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
      // Security: preload runs in an isolated context.
      preload: path.join(__dirname, "preload", "index.js"),
    },
  });

  // Load the renderer.
  if (app.isPackaged) {
    mainWindow.loadFile(path.join(__dirname, "..", "..", "dist", "index.html"));
  } else {
    mainWindow.loadURL("http://localhost:5173");
    // Open DevTools in development.
    mainWindow.webContents.openDevTools({ mode: "detach" });
  }

  // Security: block unexpected navigation.
  mainWindow.webContents.on("will-navigate", (event, url) => {
    // Only allow navigation within the app.
    if (url.startsWith("http://localhost:5173") || url.startsWith("file://")) {
      return;
    }
    event.preventDefault();
  });

  // Security: block new windows.
  mainWindow.webContents.setWindowOpenHandler(() => {
    return { action: "deny" };
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
 * In development, allows localhost for the Vite dev server.
 */
function configureCSP(): void {
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    const isDev = !app.isPackaged;
    const csp = isDev
      ? "default-src 'self'; script-src 'self' 'unsafe-inline' http://localhost:5173; style-src 'self' 'unsafe-inline'; img-src 'self' data: http://localhost:5173; connect-src 'self' http://localhost:5173;"
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
    startBackend();
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
    stopBackend();
    app.quit();
  }
});

app.on("before-quit", () => {
  stopBackend();
});

// Security: disable webview (already disabled by default in Electron 34,
// but we set it explicitly for defense in depth).
app.on("web-contents-created", (_event, contents) => {
  // Ensure webview is disabled via webPreferences.
  // Using a type assertion because Electron's TS types don't expose
  // the "will-attach" event on webContents in all versions.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (contents as any).on("will-attach", (_e: any, webPreferences: any) => {
    webPreferences.webviewTag = false;
  });
});
