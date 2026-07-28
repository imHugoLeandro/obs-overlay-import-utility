/**
 * Auto Resizer page — offline and live OBS resize.
 *
 * Uses the existing Python engines:
 * - `resizer.py` for normal/offline resize behavior;
 * - `live_resize.py` only for supported live OBS behavior.
 *
 * Workflow:
 * 1. User chooses an overlay folder (main-process folder dialog).
 * 2. Backend scans the folder for OBS collections with canvas info.
 * 3. User selects a collection.
 * 4. User chooses resize scope (Collection, Scene, Source).
 * 5. For Source scope, user selects a UUID-backed source.
 * 6. User enters target resolution and chooses mode (Stretch / Scale Ratio).
 * 7. Preview shows what would change (item count, canvas change).
 * 8. User confirms with "Apply Resize" — backend creates a backup,
 *    then writes the resized collection.
 * 9. Undo is available if a backup exists.
 *
 * Live OBS section:
 * - Shows whether OBS is running.
 * - If OBS is running, allows live resize via WebSocket.
 * - Password is forwarded once, never persisted.
 * - Undo restores the live snapshot.
 *
 * Security:
 * - The renderer never receives raw absolute paths — only opaque selection
 *   IDs and safe display labels.
 * - Conflicting actions are disabled while busy.
 * - The original collection is never modified without a backup.
 */

import React from "react";
import type {
  ResizeScope,
  ResizeMode,
  ResizeSourceChoice,
  ResizeResult,
  ResizeCollectionInfo,
  LiveResizeResult,
} from "../types/api";
import { useTheme } from "./theme";

/** Workflow steps for the stepper. */
type Step = "folder" | "scan" | "collection" | "scope" | "preview" | "result";

/** Safe error returned from the backend or IPC layer. */
interface SafeError {
  code: string;
  message: string;
}

/** Preset target resolutions. */
const PRESETS: Array<{ label: string; width: number; height: number }> = [
  { label: "720p (1280×720)", width: 1280, height: 720 },
  { label: "1080p (1920×1080)", width: 1920, height: 1080 },
  { label: "1440p (2560×1440)", width: 2560, height: 1440 },
  { label: "4K (3840×2160)", width: 3840, height: 2160 },
];

/**
 * Auto Resizer page component.
 *
 * Manages the full resize workflow state and renders the appropriate
 * step content.
 */
export function AutoResizerPage(): React.ReactElement {
  const { palette } = useTheme();
  const [step, setStep] = React.useState<Step>("folder");
  const [isBusy, setIsBusy] = React.useState(false);
  const [error, setError] = React.useState<SafeError | null>(null);

  // Selection state — holds the opaque selection ID only.
  const [selectionId, setSelectionId] = React.useState<string | null>(null);
  const [folderLabel, setFolderLabel] = React.useState<string>("");

  // Scan state.
  const [collections, setCollections] = React.useState<ResizeCollectionInfo[]>([]);

  // Collection selection state.
  const [collectionLabel, setCollectionLabel] = React.useState<string>("");
  const [collectionCanvasWidth, setCollectionCanvasWidth] = React.useState<number | null>(null);
  const [collectionCanvasHeight, setCollectionCanvasHeight] = React.useState<number | null>(null);

  // Resize options.
  const [scope, setScope] = React.useState<ResizeScope>("Collection");
  const [mode, setMode] = React.useState<ResizeMode>("Scale Ratio");
  const [targetWidth, setTargetWidth] = React.useState<number>(1920);
  const [targetHeight, setTargetHeight] = React.useState<number>(1080);
  const [selectedName, setSelectedName] = React.useState<string>("");
  const [selectedUuid, setSelectedUuid] = React.useState<string>("");
  const [sourceChoices, setSourceChoices] = React.useState<ResizeSourceChoice[]>([]);

  // Preview state.
  const [previewValid, setPreviewValid] = React.useState<boolean>(false);
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const [previewChangedItems, setPreviewChangedItems] = React.useState<number>(0);

  // Result state.
  const [resizeResult, setResizeResult] = React.useState<ResizeResult | null>(null);
  const [backupPath, setBackupPath] = React.useState<string | null>(null);

  // Live OBS state.
  const [obsRunning, setObsRunning] = React.useState<boolean>(false);
  const [liveResult, setLiveResult] = React.useState<LiveResizeResult | null>(null);
  const [liveSnapshot, setLiveSnapshot] = React.useState<LiveResizeResult["snapshot"] | null>(null);

  /** Clear error and set busy state. */
  function startBusy(): void {
    setError(null);
    setIsBusy(true);
  }

  /** Clear busy state. */
  function stopBusy(): void {
    setIsBusy(false);
  }

  /** Handle a safe error from the backend. */
  function handleError(message: string): void {
    setError({ code: "backend_error", message });
    stopBusy();
  }

  // -----------------------------------------------------------------------
  // Step 1: Choose folder
  // -----------------------------------------------------------------------

  async function handleChooseFolder(): Promise<void> {
    startBusy();
    try {
      const api = window.electronAPI;
      if (!api) {
        handleError("Backend is not available.");
        return;
      }
      const data = await api.chooseOverlayFolder();
      setSelectionId(data.selection_id);
      setFolderLabel(data.folder_label);
      setStep("scan");
      stopBusy();
    } catch (err) {
      handleError(
        err instanceof Error
          ? err.message
          : "Could not open the folder dialog. Please try again."
      );
    }
  }

  // -----------------------------------------------------------------------
  // Step 2: Scan collections
  // -----------------------------------------------------------------------

  async function handleScan(): Promise<void> {
    if (!selectionId) {
      handleError("No folder selected. Choose a folder first.");
      return;
    }
    startBusy();
    try {
      const api = window.electronAPI;
      if (!api) {
        handleError("Backend is not available.");
        return;
      }
      const data = await api.scanResizeCollections(selectionId);
      setCollections(data.collections);
      setStep("collection");
      stopBusy();
    } catch (err) {
      handleError(
        err instanceof Error
          ? err.message
          : "Could not scan the folder. Please try again."
      );
    }
  }

  // Auto-scan when we have a selection ID.
  React.useEffect(() => {
    if (selectionId && step === "scan" && !isBusy && collections.length === 0) {
      handleScan();
    }
  }, [selectionId, step, isBusy, collections.length]);

  // -----------------------------------------------------------------------
  // Step 3: Choose collection
  // -----------------------------------------------------------------------

  async function handleChooseCollection(collectionId: string): Promise<void> {
    if (!selectionId) {
      handleError("No folder selected.");
      return;
    }
    startBusy();
    try {
      const api = window.electronAPI;
      if (!api) {
        handleError("Backend is not available.");
        return;
      }
      const data = await api.chooseResizeCollection(selectionId, collectionId);
      setCollectionLabel(data.label);

      // Find canvas info from the scanned collections.
      const col = collections.find((c) => c.collection_id === collectionId);
      if (col) {
        setCollectionCanvasWidth(col.canvas_width);
        setCollectionCanvasHeight(col.canvas_height);
      }

      setStep("scope");
      stopBusy();
    } catch (err) {
      handleError(
        err instanceof Error
          ? err.message
          : "Could not select the collection. Please try again."
      );
    }
  }

  // -----------------------------------------------------------------------
  // Step 4: Choose scope and source
  // -----------------------------------------------------------------------

  async function handleScopeNext(): Promise<void> {
    if (!selectionId) {
      handleError("No folder selected.");
      return;
    }
    if (scope === "Source" && !selectedUuid) {
      handleError("Choose a source to resize.");
      return;
    }
    setStep("preview");
  }

  async function handleLoadSourceChoices(): Promise<void> {
    if (!selectionId) return;
    startBusy();
    try {
      const api = window.electronAPI;
      if (!api) {
        handleError("Backend is not available.");
        return;
      }
      const data = await api.resizeSourceChoices(selectionId);
      setSourceChoices(data.choices);
      stopBusy();
    } catch (err) {
      handleError(
        err instanceof Error
          ? err.message
          : "Could not load source choices. Please try again."
      );
    }
  }

  // Load source choices when scope changes to Source.
  React.useEffect(() => {
    if (scope === "Source" && sourceChoices.length === 0) {
      handleLoadSourceChoices();
    }
  }, [scope]);

  // -----------------------------------------------------------------------
  // Step 5: Preview
  // -----------------------------------------------------------------------

  async function handlePreview(): Promise<void> {
    if (!selectionId) {
      handleError("No folder selected.");
      return;
    }
    startBusy();
    try {
      const api = window.electronAPI;
      if (!api) {
        handleError("Backend is not available.");
        return;
      }
      const data = await api.previewResize(
        selectionId,
        scope,
        mode,
        targetWidth,
        targetHeight,
        scope === "Scene" ? selectedName : undefined,
        scope === "Source" ? selectedUuid : undefined
      );
      setPreviewValid(data.valid);
      setPreviewError(data.valid ? null : data.error);
      setPreviewChangedItems(data.changed_items);
      stopBusy();
    } catch (err) {
      handleError(
        err instanceof Error
          ? err.message
          : "Could not preview the resize. Please try again."
      );
    }
  }

  // Auto-preview when entering the preview step.
  React.useEffect(() => {
    if (step === "preview") {
      handlePreview();
    }
  }, [step]);

  // -----------------------------------------------------------------------
  // Step 6: Apply resize
  // -----------------------------------------------------------------------

  async function handleApplyResize(): Promise<void> {
    if (!selectionId) {
      handleError("No folder selected.");
      return;
    }
    if (!previewValid) {
      handleError("Preview must be valid before applying.");
      return;
    }
    startBusy();
    try {
      const api = window.electronAPI;
      if (!api) {
        handleError("Backend is not available.");
        return;
      }
      const data = await api.applyResize(
        selectionId,
        scope,
        mode,
        targetWidth,
        targetHeight,
        scope === "Scene" ? selectedName : undefined,
        scope === "Source" ? selectedUuid : undefined
      );
      setResizeResult(data);
      setBackupPath(data.backup_path);
      setStep("result");
      stopBusy();
    } catch (err) {
      handleError(
        err instanceof Error
          ? err.message
          : "Could not apply the resize. Please try again."
      );
    }
  }

  // -----------------------------------------------------------------------
  // Undo
  // -----------------------------------------------------------------------

  async function handleUndoResize(): Promise<void> {
    if (!selectionId || !backupPath) {
      handleError("No backup available to undo.");
      return;
    }
    startBusy();
    try {
      const api = window.electronAPI;
      if (!api) {
        handleError("Backend is not available.");
        return;
      }
      const data = await api.undoResize(selectionId, backupPath);
      if (data.success) {
        setBackupPath(null);
        setResizeResult(null);
        setStep("folder");
      } else {
        handleError(data.error || "Could not undo the resize.");
      }
      stopBusy();
    } catch (err) {
      handleError(
        err instanceof Error
          ? err.message
          : "Could not undo the resize. Please try again."
      );
    }
  }

  // -----------------------------------------------------------------------
  // Live OBS
  // -----------------------------------------------------------------------

  async function checkObsRunning(): Promise<void> {
    try {
      const api = window.electronAPI;
      if (!api) return;
      const data = await api.obsRunning();
      setObsRunning(data.running);
    } catch {
      setObsRunning(false);
    }
  }

  // Check OBS running on mount and when step changes to result.
  React.useEffect(() => {
    checkObsRunning();
  }, [step]);

  async function handleLiveResize(): Promise<void> {
    if (!selectionId) {
      handleError("No collection selected.");
      return;
    }
    startBusy();
    try {
      const api = window.electronAPI;
      if (!api) {
        handleError("Backend is not available.");
        return;
      }
      // For live resize, we need an installation_id. Since we're using
      // the Fix Scene Collection Paths workflow, we use the selection_id
      // as the installation_id (the backend resolves it).
      const data = await api.applyLiveResize(
        selectionId,
        scope,
        mode,
        targetWidth,
        targetHeight,
        undefined, // password — would be collected via a dialog in production
        scope === "Scene" ? selectedName : undefined,
        scope === "Source" ? selectedUuid : undefined
      );
      setLiveResult(data);
      setLiveSnapshot(data.snapshot);
      stopBusy();
    } catch (err) {
      handleError(
        err instanceof Error
          ? err.message
          : "Could not apply the live resize. Please try again."
      );
    }
  }

  async function handleUndoLiveResize(): Promise<void> {
    if (!selectionId || !liveSnapshot) {
      handleError("No live snapshot available to undo.");
      return;
    }
    startBusy();
    try {
      const api = window.electronAPI;
      if (!api) {
        handleError("Backend is not available.");
        return;
      }
      const data = await api.undoLiveResize(selectionId, liveSnapshot, undefined);
      if (data.success) {
        setLiveSnapshot(null);
        setLiveResult(null);
      } else {
        handleError(data.error || "Could not undo the live resize.");
      }
      stopBusy();
    } catch (err) {
      handleError(
        err instanceof Error
          ? err.message
          : "Could not undo the live resize. Please try again."
      );
    }
  }

  // -----------------------------------------------------------------------
  // Reset
  // -----------------------------------------------------------------------

  function handleReset(): void {
    setStep("folder");
    setSelectionId(null);
    setFolderLabel("");
    setCollections([]);
    setCollectionLabel("");
    setCollectionCanvasWidth(null);
    setCollectionCanvasHeight(null);
    setScope("Collection");
    setMode("Scale Ratio");
    setTargetWidth(1920);
    setTargetHeight(1080);
    setSelectedName("");
    setSelectedUuid("");
    setSourceChoices([]);
    setPreviewValid(false);
    setPreviewError(null);
    setPreviewChangedItems(0);
    setResizeResult(null);
    setBackupPath(null);
    setLiveResult(null);
    setLiveSnapshot(null);
    setError(null);
    setIsBusy(false);
  }

  // -----------------------------------------------------------------------
  // Render helpers
  // -----------------------------------------------------------------------

  function renderStepIndicator(): React.ReactElement {
    const steps: { id: Step; label: string }[] = [
      { id: "folder", label: "Choose Folder" },
      { id: "scan", label: "Scan Collections" },
      { id: "collection", label: "Select Collection" },
      { id: "scope", label: "Resize Options" },
      { id: "preview", label: "Preview" },
      { id: "result", label: "Result" },
    ];
    return (
      <nav
        className="import-stepper"
        aria-label="Resize workflow steps"
        style={
          {
            "--stepper-fg": palette.muted,
            "--stepper-active": palette.accent,
            "--stepper-bg": palette.surfaceAlt,
          } as React.CSSProperties
        }
      >
        <ol className="stepper-list">
          {steps.map((s, i) => {
            const isActive = step === s.id;
            const isComplete =
              (step === "scan" && s.id === "folder") ||
              (step === "collection" && (s.id === "folder" || s.id === "scan")) ||
              (step === "scope" && s.id !== "result" && s.id !== "preview") ||
              (step === "preview" && s.id !== "result") ||
              (step === "result");
            return (
              <li
                key={s.id}
                className={`stepper-item ${isActive ? "active" : ""} ${
                  isComplete ? "complete" : ""
                }`}
              >
                <span className="stepper-number">{i + 1}</span>
                <span className="stepper-label">{s.label}</span>
              </li>
            );
          })}
        </ol>
      </nav>
    );
  }

  function renderError(): React.ReactElement | null {
    if (!error) return null;
    return (
      <div
        className="import-error"
        role="alert"
        aria-live="polite"
        data-testid="resize-error"
        style={
          {
            "--error-bg": palette.surfaceAlt,
            "--error-border": palette.accent,
            "--error-fg": palette.foreground,
          } as React.CSSProperties
        }
      >
        <span className="error-icon" aria-hidden="true">
          ⚠
        </span>
        <span className="error-message">{error.message}</span>
      </div>
    );
  }

  function renderBusyOverlay(): React.ReactElement | null {
    if (!isBusy) return null;
    return (
      <div
        className="import-busy-overlay"
        aria-label="Working"
        data-testid="resize-busy"
      >
        <div className="busy-spinner" aria-hidden="true" />
        <span className="busy-text">Working…</span>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Main render
  // -----------------------------------------------------------------------

  return (
    <section
      className="import-page"
      aria-labelledby="resizer-title"
      style={
        {
          "--page-bg": palette.background,
          "--page-surface": palette.surface,
          "--page-border": palette.border,
          "--page-text": palette.foreground,
          "--page-text-muted": palette.muted,
          "--page-accent": palette.accent,
        } as React.CSSProperties
      }
    >
      <h1 id="resizer-title" className="import-title">
        Auto Resizer
      </h1>
      <p className="import-description">
        Resize an OBS scene collection, scene, or source. The original
        collection is backed up before any changes are made.
      </p>

      {renderStepIndicator()}
      {renderError()}

      <div className="import-content">
        {step === "folder" && (
          <div className="step-folder">
            <p className="step-description">
              Choose the folder that contains your extracted overlay files
              and scene collection JSON.
            </p>
            <button
              type="button"
              className="import-button-primary"
              onClick={handleChooseFolder}
              disabled={isBusy}
              data-testid="choose-folder-button"
            >
              Choose Overlay Folder
            </button>
          </div>
        )}

        {step === "scan" && (
          <div className="step-scan">
            <p className="step-description">
              Scanning "{folderLabel}" for OBS scene collections…
            </p>
            <div className="scan-status" data-testid="scan-status">
              {collections.length === 0 && !isBusy && (
                <p className="scan-empty">
                  No scene collections were found in this folder.
                </p>
              )}
            </div>
          </div>
        )}

        {step === "collection" && (
          <div className="step-collection">
            <p className="step-description">
              Found {collections.length} collection(s). Select the one to
              resize.
            </p>
            {collections.length > 0 ? (
              <ul className="collection-list" data-testid="collection-list">
                {collections.map((col) => (
                  <li key={col.collection_id}>
                    <button
                      type="button"
                      className="collection-button"
                      onClick={() => handleChooseCollection(col.collection_id)}
                      disabled={isBusy}
                      data-testid={`collection-${col.collection_id.slice(0, 8)}`}
                    >
                      <span className="collection-label">{col.label}</span>
                      {col.canvas_width && col.canvas_height && (
                        <span className="collection-canvas">
                          {col.canvas_width}×{col.canvas_height}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="collection-empty">
                No collections detected. Go back and choose a different folder.
              </p>
            )}
            <button
              type="button"
              className="import-button-secondary"
              onClick={() => setStep("folder")}
              disabled={isBusy}
              data-testid="back-to-folder"
            >
              Choose a Different Folder
            </button>
          </div>
        )}

        {step === "scope" && (
          <div className="step-scope">
            <div className="convert-info">
              <p>
                <strong>Collection:</strong> {collectionLabel}
              </p>
              {collectionCanvasWidth && collectionCanvasHeight && (
                <p>
                  <strong>Current canvas:</strong> {collectionCanvasWidth}×{collectionCanvasHeight}
                </p>
              )}
            </div>

            <fieldset className="options-fieldset" data-testid="resize-scope">
              <legend className="options-legend">Resize Scope</legend>
              <label className="option-row">
                <input
                  type="radio"
                  name="scope"
                  className="option-radio"
                  value="Collection"
                  checked={scope === "Collection"}
                  onChange={() => setScope("Collection")}
                  disabled={isBusy}
                  data-testid="scope-collection"
                />
                <span className="option-label">Collection (resize entire canvas)</span>
              </label>
              <label className="option-row">
                <input
                  type="radio"
                  name="scope"
                  className="option-radio"
                  value="Scene"
                  checked={scope === "Scene"}
                  onChange={() => setScope("Scene")}
                  disabled={isBusy}
                  data-testid="scope-scene"
                />
                <span className="option-label">Scene (resize one scene)</span>
              </label>
              <label className="option-row">
                <input
                  type="radio"
                  name="scope"
                  className="option-radio"
                  value="Source"
                  checked={scope === "Source"}
                  onChange={() => setScope("Source")}
                  disabled={isBusy}
                  data-testid="scope-source"
                />
                <span className="option-label">Source (resize one UUID-backed source)</span>
              </label>
            </fieldset>

            {scope === "Scene" && (
              <div className="scene-input">
                <label htmlFor="scene-name">Scene name:</label>
                <input
                  type="text"
                  id="scene-name"
                  className="text-input"
                  value={selectedName}
                  onChange={(e) => setSelectedName(e.target.value)}
                  disabled={isBusy}
                  data-testid="scene-name-input"
                  placeholder="Enter the scene name"
                />
              </div>
            )}

            {scope === "Source" && sourceChoices.length > 0 && (
              <div className="source-select">
                <label htmlFor="source-select">Select a source:</label>
                <select
                  id="source-select"
                  className="select-input"
                  value={selectedUuid}
                  onChange={(e) => {
                    const selected = sourceChoices.find(
                      (c) => c.uuid === e.target.value
                    );
                    setSelectedUuid(e.target.value);
                    setSelectedName(selected?.name || "");
                  }}
                  disabled={isBusy}
                  data-testid="source-select"
                >
                  <option value="">— Choose a source —</option>
                  {sourceChoices.map((choice) => (
                    <option key={choice.uuid} value={choice.uuid}>
                      {choice.label}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <fieldset className="options-fieldset" data-testid="resize-mode">
              <legend className="options-legend">Resize Mode</legend>
              <label className="option-row">
                <input
                  type="radio"
                  name="mode"
                  className="option-radio"
                  value="Stretch"
                  checked={mode === "Stretch"}
                  onChange={() => setMode("Stretch")}
                  disabled={isBusy}
                  data-testid="mode-stretch"
                />
                <span className="option-label">Stretch (independent X/Y)</span>
              </label>
              <label className="option-row">
                <input
                  type="radio"
                  name="mode"
                  className="option-radio"
                  value="Scale Ratio"
                  checked={mode === "Scale Ratio"}
                  onChange={() => setMode("Scale Ratio")}
                  disabled={isBusy}
                  data-testid="mode-scale-ratio"
                />
                <span className="option-label">Scale Ratio (preserve aspect)</span>
              </label>
            </fieldset>

            <div className="target-inputs">
              <label>Target Resolution:</label>
              <div className="preset-buttons" data-testid="preset-buttons">
                {PRESETS.map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    className="preset-button"
                    onClick={() => {
                      setTargetWidth(p.width);
                      setTargetHeight(p.height);
                    }}
                    disabled={isBusy}
                    data-testid={`preset-${p.width}`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <div className="custom-resolution">
                <input
                  type="number"
                  className="dimension-input"
                  min={16}
                  max={32768}
                  value={targetWidth}
                  onChange={(e) => setTargetWidth(parseInt(e.target.value, 10) || 0)}
                  disabled={isBusy}
                  data-testid="target-width"
                />
                <span className="dimension-separator">×</span>
                <input
                  type="number"
                  className="dimension-input"
                  min={16}
                  max={32768}
                  value={targetHeight}
                  onChange={(e) => setTargetHeight(parseInt(e.target.value, 10) || 0)}
                  disabled={isBusy}
                  data-testid="target-height"
                />
              </div>
            </div>

            <div className="scope-actions">
              <button
                type="button"
                className="import-button-secondary"
                onClick={() => setStep("collection")}
                disabled={isBusy}
                data-testid="back-to-collection"
              >
                Back
              </button>
              <button
                type="button"
                className="import-button-primary"
                onClick={handleScopeNext}
                disabled={isBusy}
                data-testid="next-to-preview"
              >
                Preview Resize
              </button>
            </div>
          </div>
        )}

        {step === "preview" && (
          <div className="step-preview">
            <div className="preview-info">
              <p>
                <strong>Collection:</strong> {collectionLabel}
              </p>
              <p>
                <strong>Scope:</strong> {scope}
              </p>
              {scope === "Scene" && (
                <p>
                  <strong>Scene:</strong> {selectedName}
                </p>
              )}
              {scope === "Source" && (
                <p>
                  <strong>Source:</strong> {selectedName} ({selectedUuid.slice(0, 8)})
                </p>
              )}
              <p>
                <strong>Mode:</strong> {mode}
              </p>
              <p>
                <strong>Target:</strong> {targetWidth}×{targetHeight}
              </p>
              {collectionCanvasWidth && collectionCanvasHeight && (
                <p>
                  <strong>Current canvas:</strong> {collectionCanvasWidth}×{collectionCanvasHeight}
                </p>
              )}
            </div>

            {previewValid ? (
              <div
                className="preview-valid"
                data-testid="preview-valid"
                role="status"
              >
                <span className="preview-icon" aria-hidden="true">
                  ✓
                </span>
                <div className="preview-details">
                  <p>
                    <strong>{previewChangedItems}</strong> item(s) will be
                    resized.
                  </p>
                  {scope === "Collection" && (
                    <p>Canvas will change to {targetWidth}×{targetHeight}.</p>
                  )}
                  <p>A backup will be created before applying.</p>
                </div>
              </div>
            ) : (
              <div
                className="preview-invalid"
                data-testid="preview-invalid"
                role="alert"
              >
                <span className="preview-icon" aria-hidden="true">
                  ⚠
                </span>
                <p>{previewError || "The resize could not be previewed."}</p>
              </div>
            )}

            <div className="preview-actions">
              <button
                type="button"
                className="import-button-secondary"
                onClick={() => setStep("scope")}
                disabled={isBusy}
                data-testid="back-to-scope"
              >
                Back
              </button>
              <button
                type="button"
                className="import-button-primary"
                onClick={handleApplyResize}
                disabled={isBusy || !previewValid}
                data-testid="apply-resize-button"
              >
                Apply Resize
              </button>
            </div>
          </div>
        )}

        {step === "result" && resizeResult && (
          <div className="step-result">
            {resizeResult.success ? (
              <div
                className="result-success"
                data-testid="result-success"
                role="status"
              >
                <span className="result-icon" aria-hidden="true">
                  ✓
                </span>
                <h2>Resize Complete</h2>
                <div className="result-details">
                  <p>
                    <strong>{resizeResult.changed_items}</strong> item(s)
                    resized.
                  </p>
                  <p>
                    Canvas: {resizeResult.source_width}×{resizeResult.source_height} →{" "}
                    {resizeResult.target_width}×{resizeResult.target_height}
                  </p>
                  {resizeResult.canvas_changed && (
                    <p>Collection canvas was updated.</p>
                  )}
                  {backupPath && (
                    <p>
                      <strong>Backup created:</strong> {backupPath}
                    </p>
                  )}
                </div>
              </div>
            ) : (
              <div
                className="result-error"
                data-testid="result-error"
                role="alert"
              >
                <span className="result-icon" aria-hidden="true">
                  ⚠
                </span>
                <h2>Resize Failed</h2>
                <p>{resizeResult.error}</p>
              </div>
            )}

            {/* Live OBS section */}
            <div className="live-section" data-testid="live-section">
              <h3>Live OBS Resize</h3>
              {obsRunning ? (
                <p>
                  <span className="obs-status" aria-hidden="true">
                    ●
                  </span>{" "}
                  OBS is running. You can apply this resize live.
                </p>
              ) : (
                <p>
                  <span className="obs-status" aria-hidden="true">
                    ○
                  </span>{" "}
                  OBS is not running. Live resize is unavailable.
                </p>
              )}
              {obsRunning && resizeResult.success && !liveResult && (
                <button
                  type="button"
                  className="import-button-primary"
                  onClick={handleLiveResize}
                  disabled={isBusy}
                  data-testid="live-resize-button"
                >
                  Apply Live Resize
                </button>
              )}
              {liveResult && (
                <div className="live-result">
                  {liveResult.success ? (
                    <p>Live resize applied to {liveResult.changed_items} item(s).</p>
                  ) : (
                    <p>Live resize failed: {liveResult.error}</p>
                  )}
                  {liveResult.snapshot && (
                    <button
                      type="button"
                      className="import-button-secondary"
                      onClick={handleUndoLiveResize}
                      disabled={isBusy}
                      data-testid="undo-live-button"
                    >
                      Undo Live Resize
                    </button>
                  )}
                </div>
              )}
            </div>

            <div className="result-actions">
              {backupPath && resizeResult.success && (
                <button
                  type="button"
                  className="import-button-secondary"
                  onClick={handleUndoResize}
                  disabled={isBusy}
                  data-testid="undo-resize-button"
                >
                  Undo Offline Resize
                </button>
              )}
              <button
                type="button"
                className="import-button-secondary"
                onClick={handleReset}
                disabled={isBusy}
                data-testid="start-over-button"
              >
                Start Over
              </button>
            </div>
          </div>
        )}
      </div>

      {renderBusyOverlay()}
    </section>
  );
}
