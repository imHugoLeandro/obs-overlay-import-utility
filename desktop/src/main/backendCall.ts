/**
 * Backend call helper for the Electron main process.
 *
 * This module provides a single function for calling the Python backend
 * that preserves trusted expected error codes/messages from Python,
 * while converting transport failures, backend exits, timeouts, and
 * unexpected exceptions into a single generic customer-safe error.
 *
 * Expected errors (structured { code, message } from Python) are
 * re-thrown as-is so the renderer can display the useful safe message.
 *
 * Transport failures, backend exit, timeout, malformed backend response,
 * or unexpected exception become:
 *   "The backend is unavailable. Restart the application and try again."
 */

import type { BackendCommand } from "./contracts/backendCommands";
import type { BackendTransport } from "./transport";

/** Generic customer-safe error for backend unavailability. */
export const BACKEND_UNAVAILABLE_ERROR =
  "The backend is unavailable. Restart the application and try again.";

/**
 * Explicit operation budgets. Small read-only checks fail quickly; archive,
 * export, and resize operations receive enough time for legitimate local I/O.
 */
const BACKEND_TIMEOUT_MS: Record<BackendCommand, number> = {
  health: 5_000,
  app_info: 5_000,
  obs_running: 5_000,
  scan_collections: 30_000,
  scan_resize_collections: 30_000,
  resize_source_choices: 30_000,
  resize_scene_choices: 30_000,
  device_requirements: 30_000,
  device_candidates: 30_000,
  list_export_collections: 30_000,
  export_inventory: 30_000,
  convert_collection: 60_000,
  apply_device_choices: 60_000,
  activate_collection: 60_000,
  preview_resize: 60_000,
  undo_resize: 60_000,
  import_streamlabs: 120_000,
  automatic_import: 120_000,
  build_export_plan: 120_000,
  confirm_export: 120_000,
  resize_collection: 120_000,
};

/**
 * Typed internal expected-backend error.
 *
 * Contains only safe `code` and `message` — never tracebacks, stack
 * traces, raw diagnostics, or selected absolute paths.
 *
 * Created when the Python backend returns a structured
 * `{ type: "error", error: { code, message } }` response.
 * Transport failures, backend exit, timeout, malformed response, or
 * unexpected exception become BACKEND_UNAVAILABLE_ERROR instead.
 */
export class ExpectedBackendError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "ExpectedBackendError";
    this.code = code;
  }
}

/**
 * Call the Python backend and return the result data.
 *
 * @param backend The BackendTransport instance.
 * @param command The backend command to invoke.
 * @param params Optional parameters to forward.
 * @returns The result data from the backend.
 * @throws {ExpectedBackendError} with the backend's expected error code
 *   and message (preserved, customer-safe — no tracebacks or raw paths).
 * @throws {Error} with BACKEND_UNAVAILABLE_ERROR for transport/unexpected
 *   failures.
 */
export async function callBackend(
  backend: BackendTransport,
  command: BackendCommand,
  params?: Record<string, unknown>
): Promise<unknown> {
  let response: unknown;
  try {
    response = await backend.sendRequest(command, params, BACKEND_TIMEOUT_MS[command]);
  } catch {
    // Transport failure, backend exit, timeout, etc.
    throw new Error(BACKEND_UNAVAILABLE_ERROR);
  }

  const resp = response as {
    type?: string;
    data?: unknown;
    error?: { code?: string; message?: string };
  };

  // Malformed backend response.
  if (!resp || typeof resp !== "object" || typeof resp.type !== "string") {
    throw new Error(BACKEND_UNAVAILABLE_ERROR);
  }

  if (resp.type === "result") {
    return resp.data;
  }

  if (resp.type === "error" && resp.error?.message) {
    // Preserve the expected error code and message from Python.
    // The message is already customer-safe (no tracebacks, no raw paths).
    throw new ExpectedBackendError(
      resp.error.code ?? "backend_error",
      resp.error.message
    );
  }

  // Unexpected error shape.
  throw new Error(BACKEND_UNAVAILABLE_ERROR);
}
