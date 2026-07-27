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
  /** Zero-based index of the collection in the scan results. */
  index: number;
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

/** Result of choosing a collection. */
export interface ChooseCollectionResult {
  selection_id: string;
  collection_label: string;
}

/** An ambiguous match returned by the conversion. */
export interface AmbiguousMatch {
  source_name: string;
  original_path: string;
  candidates: string[];
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

/**
 * Typed API surface exposed to the renderer via `contextBridge`.
 *
 * Only the finite set of commands below is exposed.  There is no shell,
 * file-read, or generic function-call endpoint.
 */
export interface ElectronAPI {
  health: () => Promise<HealthData>;
  appInfo: () => Promise<AppInfoData>;
  /**
   * Store an overlay folder path (resolved by the main process folder
   * dialog) and return an opaque selection ID plus a safe label.
   */
  chooseFolder: (folderPath: string) => Promise<{
    selection_id: string;
    folder_label: string;
  }>;
  /**
   * Scan the selected folder for OBS scene collections.
   * Returns detected collections with safe relative labels.
   */
  scanCollections: (selectionId: string) => Promise<ScanCollectionsResult>;
  /**
   * Select one detected collection by its index.
   */
  chooseCollection: (
    selectionId: string,
    collectionIndex: number
  ) => Promise<ChooseCollectionResult>;
  /**
   * Run path-fix conversion on the selected collection.
   * The original collection is never modified.
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
