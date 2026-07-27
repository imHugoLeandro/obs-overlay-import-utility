/**
 * Backend transport for the Electron main process.
 *
 * Manages the Python backend subprocess and JSON-lines protocol.
 * Extracted into a separate module for testability.
 *
 * - Buffers stdout across chunks and parses complete newline-delimited JSON.
 * - Supports concurrent requests via a pending-request map keyed by request ID.
 * - Rejects all pending requests if the backend exits, errors, or stdin fails.
 * - Clears request timeouts after success/failure.
 */

import * as child_process from "child_process";

/** A parsed JSON-lines response from the backend. */
export interface BackendResponse {
  request_id: string;
  type: string;
  data?: Record<string, unknown>;
  error?: { code: string; message: string };
}

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
  timer: NodeJS.Timeout;
}

/**
 * Manages the Python backend subprocess and JSON-lines protocol.
 */
export class BackendTransport {
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
  start(pythonExec: string, pythonPath: string): void {
    if (this.pyProcess) {
      return;
    }

    this.pyProcess = child_process.spawn(
      pythonExec,
      ["-u", "-m", "obs_overlay_import_utility.desktop_backend"],
      {
        stdio: ["pipe", "pipe", "pipe"],
        env: {
          ...process.env,
          PYTHONPATH: pythonPath,
        },
      }
    );

    this.pyStdin = this.pyProcess.stdin;
    this.pyStdout = this.pyProcess.stdout;

    if (this.pyProcess.stderr) {
      this.pyProcess.stderr.on("data", (data: Buffer) => {
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
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error(`Backend request timed out: ${command}`));
      }, 10000);

      this.pending.set(requestId, { resolve, reject, timer });

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
   * This is the core protocol routing logic — tested directly in tests.
   */
  handleStdout(data: Buffer): void {
    this.stdoutBuffer += data.toString();

    let newlineIndex: number;
    while ((newlineIndex = this.stdoutBuffer.indexOf("\n")) !== -1) {
      const line = this.stdoutBuffer.slice(0, newlineIndex).trim();
      this.stdoutBuffer = this.stdoutBuffer.slice(newlineIndex + 1);

      if (!line) {
        continue;
      }

      try {
        const response = JSON.parse(line) as BackendResponse;
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
  rejectAllPending(error: Error): void {
    this.pending.forEach((pending, requestId) => {
      clearTimeout(pending.timer);
      this.pending.delete(requestId);
      pending.reject(error);
    });
  }

  /** Check if the backend process is running. */
  isRunning(): boolean {
    return this.pyProcess !== null;
  }

  /** Get the number of pending requests. */
  getPendingCount(): number {
    return this.pending.size;
  }
}
