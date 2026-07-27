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

import type { BackendTransport } from "./transport";

/** Generic customer-safe error for backend unavailability. */
export const BACKEND_UNAVAILABLE_ERROR =
  "The backend is unavailable. Restart the application and try again.";

/**
 * Call the Python backend and return the result data.
 *
 * @param backend The BackendTransport instance.
 * @param command The backend command to invoke.
 * @param params Optional parameters to forward.
 * @returns The result data from the backend.
 * @throws Error with the backend's expected error message (preserved),
 *   or BACKEND_UNAVAILABLE_ERROR for transport/unexpected failures.
 */
export async function callBackend(
  backend: BackendTransport,
  command: string,
  params?: Record<string, unknown>
): Promise<unknown> {
  let response: unknown;
  try {
    response = await backend.sendRequest(command, params);
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
    throw new Error(resp.error.message);
  }

  // Unexpected error shape.
  throw new Error(BACKEND_UNAVAILABLE_ERROR);
}
