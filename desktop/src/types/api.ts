/**
 * Shared type definitions for the Electron desktop shell.
 *
 * These types are imported by both the preload script (which validates
 * payloads before forwarding them) and the renderer (which consumes the
 * typed API exposed via `contextBridge`).
 */

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

/** A detected OBS scene collection with a safe relative label. */
export interface DetectedCollection {
  /** Opaque collection ID — safe to send to the renderer. */
  collection_id: string;
  /** Human-readable label relative to the selected folder. */
  label: string;
}

/** Result of scanning a folder for scene collections. */
export interface ScanCollectionsResult {
  selection_id: string;
  folder_label: string;
  collections: DetectedCollection[];
  count: number;
}

/** The conversion result returned by `convert_collection`. */
export interface ConvertResult {
  success: boolean;
  changed: number;
  unchanged: number;
  missing: string[];
  ambiguous: AmbiguousMatch[];
  indexed_files: number;
  candidate_paths: number;
  /** Relative output filename when successful; absent on failure. */
  output_filename?: string;
  /** Relative output path when successful; absent on failure. */
  output_path?: string;
  /** Error message when unsuccessful; absent on success. */
  error?: string;
}

/** An ambiguous match returned by the conversion. */
export interface AmbiguousMatch {
  source_name: string;
  original_path: string;
  candidates: string[];
}

/**
 * Typed API surface exposed to the renderer via `contextBridge`.
 *
 * Only the finite set of commands below is exposed.  There is no shell,
 * file-read, or generic function-call endpoint.
 *
 * The renderer never sends or receives raw absolute paths — only opaque
 * selection IDs and collection IDs plus safe display labels.
 */
export interface ElectronAPI {
  health: () => Promise<HealthData>;
  appInfo: () => Promise<AppInfoData>;
  /**
   * Open a native folder dialog (no renderer arguments) and store the
   * selected folder in the Electron main-process selection store.
   * Returns an opaque selection ID plus a safe folder label.
   */
  chooseOverlayFolder: () => Promise<{
    selection_id: string;
    folder_label: string;
  }>;
  /**
   * Scan the selected folder for OBS scene collections.
   * Returns detected collections with opaque collection IDs and safe
   * relative labels only.
   */
  scanCollections: (selectionId: string) => Promise<ScanCollectionsResult>;
  /**
   * Select one detected collection by its opaque collection ID.
   * Verifies that the collection ID belongs to the selection.
   */
  chooseCollection: (
    selectionId: string,
    collectionId: string
  ) => Promise<{ selection_id: string; collection_label: string }>;
  /**
   * Run path-fix conversion on the selected collection.
   * The original collection is never modified.
   * Returns a structured result with success/failure details.
   */
  convertCollection: (
    selectionId: string,
    strict: boolean,
    caseSensitive: boolean
  ) => Promise<ConvertResult>;
}

/** Augment the global `Window` type so the renderer can use `window.electronAPI`. */
declare global {
  interface Window {
    electronAPI: ElectronAPI;
  }
}
