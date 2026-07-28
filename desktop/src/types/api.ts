/**
 * Shared type definitions for the Electron desktop shell.
 *
 * These types are imported by both the preload script (which validates
 * payloads before forwarding them) and the renderer (which consumes the
 * typed API exposed via `contextBridge`).
 *
 * Security: the renderer never sends or receives raw absolute paths —
 * only opaque selection IDs, collection IDs, plan IDs, and safe display
 * labels.  Electron main is the sole owner of concrete filesystem paths.
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

/** Result of importing a Streamlabs .overlay archive. */
export interface StreamlabsImportResult {
  success: boolean;
  installation_id: string | null;
  collection_name: string;
  canvas_width: number;
  canvas_height: number;
  imported_sources: number;
  skipped_sources: string[];
  profile_name: string | null;
  error: string | null;
}

/** Result of an automatic import (portable/OBS/Streamlabs). */
export interface AutomaticImportResult {
  success: boolean;
  installation_id: string | null;
  kind: string;
  collection_name: string;
  canvas_width: number | null;
  canvas_height: number | null;
  profile_name: string | null;
  error: string | null;
  conversion: ConvertResult | null;
}

/** A configurable device source requirement. */
export interface DeviceRequirement {
  key: string;
  name: string;
  source_id: string;
  kind: string;
}

/** A reusable local device candidate. */
export interface DeviceCandidate {
  candidate_id: string;
  source_id: string;
  label: string;
  kind: string;
}

/** Result of applying device choices. */
export interface DeviceApplyResult {
  success: boolean;
  error: string | null;
}

/** Result of checking whether OBS is running. */
export interface ObsRunningResult {
  running: boolean;
}

/** Result of activating a collection in OBS. */
export interface ActivateResult {
  success: boolean;
  error: string | null;
}

/** An OBS scene collection available for export. */
export interface ExportCollectionInfo {
  collectionId: string;
  label: string;
}

/** Result of choosing an export destination folder. */
export interface ExportDestinationInfo {
  destination_id: string;
  destination_label: string;
}

/** A single item in an export inventory. */
export interface ExportInventoryItem {
  category: string;
  size: number;
  source_name: string;
}

/** A dependency report entry for remote resources. */
export interface RemoteResourceEntry {
  host: string;
  sensitive: boolean;
}

/** A dependency report for an export plan. */
export interface ExportDependencyReport {
  fonts: string[];
  devices: Array<Record<string, string>>;
  remote_resources: RemoteResourceEntry[];
  plugin_source_ids: Array<Record<string, string>>;
  plugin_filter_ids: Array<Record<string, string>>;
}

/** A sanitized export inventory view (frozen plan summary). */
export interface ExportInventory {
  plan_id: string;
  collection_label: string;
  collection_stem: string;
  compressed: boolean;
  source_references: number;
  total_bytes: number;
  scene_count: number;
  source_count: number;
  browser_files: number;
  canvas_width: number | null;
  canvas_height: number | null;
  missing_references: string[];
  dependency_report: ExportDependencyReport;
  items: ExportInventoryItem[];
}

/** Verification status of an exported package. */
export interface ExportVerification {
  ok: boolean;
  errors: string[];
}

/** Result of confirming (executing) an export plan. */
export interface ExportResult {
  success: boolean;
  already_executed: boolean;
  copied_files: number;
  uncompressed_bytes: number;
  source_references: number;
  skipped_references: string[];
  verification: ExportVerification | null;
  output_label: string | null;
  error: string | null;
}

/** Resize scope: Collection, Scene, or Source. */
export type ResizeScope = "Collection" | "Scene" | "Source";

/** Resize mode: Stretch or Scale Ratio. */
export type ResizeMode = "Stretch" | "Scale Ratio";

/** A UUID-backed source choice for Source-scope resize. */
export interface ResizeSourceChoice {
  label: string;
  name: string;
  uuid: string;
}

/** Result of an offline resize operation. */
export interface ResizeResult {
  success: boolean;
  error: string | null;
  changed_items: number;
  source_width: number;
  source_height: number;
  target_width: number;
  target_height: number;
  canvas_changed: boolean;
  /** Relative backup path (safe for renderer). */
  backup_path: string | null;
}

/** A live transform backup entry. */
export interface LiveTransformBackup {
  scene_name: string;
  scene_item_id: number;
  transform: Record<string, unknown>;
}

/** A live resize snapshot for undo. */
export interface LiveResizeSnapshot {
  collection_name: string;
  transforms: LiveTransformBackup[];
  video_settings: Record<string, unknown> | null;
}

/** Result of a live (OBS WebSocket) resize operation. */
export interface LiveResizeResult {
  success: boolean;
  error: string | null;
  changed_items: number;
  source_width: number;
  source_height: number;
  target_width: number;
  target_height: number;
  canvas_changed: boolean;
  snapshot: LiveResizeSnapshot | null;
}

/** A detected scene collection with canvas info for resize. */
export interface ResizeCollectionInfo {
  collection_id: string;
  label: string;
  canvas_width: number | null;
  canvas_height: number | null;
  source_count: number;
  scene_count: number;
}

/**
 * Typed API surface exposed to the renderer via `contextBridge`.
 *
 * Only the finite set of commands below is exposed.  There is no shell,
 * file-read, or generic function-call endpoint.
 *
 * The renderer never sends or receives raw absolute paths — only opaque
 * selection IDs, collection IDs, plan IDs, and safe display labels.
 * Electron main is the sole owner of concrete filesystem paths.
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
   * Open a native file dialog with a strict .overlay filter and store
   * the selected archive in the Electron main-process selection store.
   */
  chooseStreamlabsOverlay: () => Promise<{
    selection_id: string;
    folder_label: string;
  }>;
  /**
   * Open a native folder dialog for automatic import and store the
   * selected folder in the Electron main-process selection store.
   */
  chooseAutomaticFolder: () => Promise<{
    selection_id: string;
    folder_label: string;
  }>;
  /**
   * Scan the selected folder for OBS scene collections.
   */
  scanCollections: (selectionId: string) => Promise<ScanCollectionsResult>;
  /**
   * Select one detected collection by its opaque collection ID.
   */
  chooseCollection: (
    selectionId: string,
    collectionId: string
  ) => Promise<{ selection_id: string; collection_label: string }>;
  /**
   * Run path-fix conversion on the selected collection.
   */
  convertCollection: (
    selectionId: string,
    strict: boolean,
    caseSensitive: boolean
  ) => Promise<ConvertResult>;
  /**
   * Import a Streamlabs .overlay archive.
   * Takes only an opaque selection_id — Electron main resolves paths.
   */
  importStreamlabs: (selectionId: string) => Promise<StreamlabsImportResult>;
  /**
   * Detect and import one supported package.
   * Takes only an opaque selection_id — Electron main resolves paths.
   */
  automaticImport: (
    selectionId: string,
    strict: boolean,
    caseSensitive: boolean
  ) => Promise<AutomaticImportResult>;
  /**
   * List configurable device sources for an installed collection.
   * Takes only an opaque installation_id — never a raw path.
   */
  deviceRequirements: (
    installationId: string
  ) => Promise<{ requirements: DeviceRequirement[]; count: number }>;
  /**
   * List reusable local device settings for a given installation.
   * Takes only an opaque installation_id — never a raw path.
   */
  deviceCandidates: (
    installationId: string
  ) => Promise<{ candidates: DeviceCandidate[]; count: number }>;
  /**
   * Apply selected device settings to an installed collection.
   * Takes only an opaque installation_id — never a raw path.
   */
  applyDeviceChoices: (
    installationId: string,
    choices: Record<string, unknown>
  ) => Promise<DeviceApplyResult>;
  /**
   * Check whether OBS appears to be running.
   */
  obsRunning: () => Promise<ObsRunningResult>;
  /**
   * Activate a collection in OBS via WebSocket (optional, explicit action).
   * Takes only an opaque installation_id — never a raw collection name or path.
   */
  activateCollection: (
    installationId: string,
    password?: string
  ) => Promise<ActivateResult>;
  /**
   * List OBS scene collections available for export.
   * Takes no renderer path — Electron main resolves the OBS scenes directory.
   */
  listExportCollections: () => Promise<{
    collections: ExportCollectionInfo[];
    count: number;
  }>;
  /**
   * Open a native folder dialog for the export destination.
   * Returns an opaque destination_id and a safe label — never a raw path.
   */
  chooseExportDestination: () => Promise<ExportDestinationInfo>;
  /**
   * Build a frozen, backend-held export plan.
   * Takes only opaque collection_id and destination_id — never raw paths.
   */
  buildExportPlan: (
    collectionId: string,
    destinationId: string,
    compressed: boolean
  ) => Promise<ExportInventory>;
  /**
   * Return a sanitized inventory view for an existing plan.
   */
  exportInventory: (planId: string) => Promise<ExportInventory>;
  /**
   * Execute a frozen export plan by opaque plan_id.
   */
  confirmExport: (planId: string) => Promise<ExportResult>;
  /**
   * Scan a folder for OBS collections with canvas info for resize.
   * Returns opaque collection IDs and safe labels only.
   */
  scanResizeCollections: (selectionId: string) => Promise<{
    collections: ResizeCollectionInfo[];
    count: number;
  }>;
  /**
   * Choose a collection for resize by opaque collection ID.
   */
  chooseResizeCollection: (
    selectionId: string,
    collectionId: string
  ) => Promise<{ collection_id: string; label: string }>;
  /**
   * List UUID-backed source choices for Source-scope resize.
   */
  resizeSourceChoices: (
    selectionId: string
  ) => Promise<{ choices: ResizeSourceChoice[]; count: number }>;
  /**
   * Preview an offline resize (validates inputs, returns what would change).
   */
  previewResize: (
    selectionId: string,
    scope: ResizeScope,
    mode: ResizeMode,
    targetWidth: number,
    targetHeight: number,
    selectedName?: string,
    selectedUuid?: string
  ) => Promise<{ valid: boolean; error: string | null; source_width: number; source_height: number; changed_items: number }>;
  /**
   * Execute an offline resize. Creates a backup before writing.
   * Requires explicit confirmation (caller must have called previewResize first).
   */
  applyResize: (
    selectionId: string,
    scope: ResizeScope,
    mode: ResizeMode,
    targetWidth: number,
    targetHeight: number,
    selectedName?: string,
    selectedUuid?: string
  ) => Promise<ResizeResult>;
  /**
   * Undo a resize by restoring a backup.
   */
  undoResize: (
    selectionId: string,
    backupPath: string
  ) => Promise<{ success: boolean; error: string | null }>;
  /**
   * Execute a live OBS resize through WebSocket.
   * Password is forwarded once, never persisted.
   */
  applyLiveResize: (
    installationId: string,
    scope: ResizeScope,
    mode: ResizeMode,
    targetWidth: number,
    targetHeight: number,
    password?: string,
    selectedName?: string,
    selectedUuid?: string
  ) => Promise<LiveResizeResult>;
  /**
   * Undo a live OBS resize using a snapshot.
   */
  undoLiveResize: (
    installationId: string,
    snapshot: LiveResizeSnapshot,
    password?: string
  ) => Promise<{ success: boolean; error: string | null }>;
}

/** Augment the global `Window` type so the renderer can use `window.electronAPI`. */
declare global {
  interface Window {
    electronAPI: ElectronAPI;
  }
}
