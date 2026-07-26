/**
 * Shared type definitions for the Electron desktop shell.
 *
 * These types are imported by both the preload script (which validates
 * payloads before forwarding them) and the renderer (which consumes the
 * typed API exposed via `contextBridge`).
 */

/** A successful response payload. */
export interface ResultData {
  [key: string]: unknown;
}

/** A structured error payload. */
export interface ErrorData {
  code: string;
  message: string;
}

/** A result response from the backend. */
export interface ResultResponse {
  request_id: string;
  type: "result";
  data: ResultData;
}

/** An error response from the backend. */
export interface ErrorResponse {
  request_id: string;
  type: "error";
  error: ErrorData;
}

/** Union of all possible backend responses. */
export type BackendResponse = ResultResponse | ErrorResponse;

/** The health payload returned by the `health` command. */
export interface HealthData {
  status: "ok";
  pid: number;
  uptime_seconds: number;
  python_version: string;
}

/** The app-info payload returned by the `app_info` command. */
export interface AppInfoData {
  name: string;
  version: string;
}

/**
 * Typed API surface exposed to the renderer via `contextBridge`.
 *
 * Only `health` and `app_info` are exposed.  There is no shell, file-read,
 * or generic function-call endpoint.
 */
export interface ElectronAPI {
  health: () => Promise<HealthData>;
  appInfo: () => Promise<AppInfoData>;
}

/** Augment the global `Window` type so the renderer can use `window.electronAPI`. */
declare global {
  // eslint-disable-next-line @typescript-eslint/no-empty-object-types
  interface Window {
    electronAPI: ElectronAPI;
  }
}
