/**
 * Import page — "Fix Scene Collection Paths" workflow.
 *
 * This is the functional implementation of Stage 2B: the Fix Scene
 * Collection Paths import workflow.
 *
 * Workflow:
 * 1. User chooses an extracted overlay folder (main-process folder dialog).
 * 2. Backend scans the folder using existing `find_scene_collections()`.
 * 3. Detected valid OBS collection JSON files are shown with readable
 *    relative labels.
 * 4. User selects one detected collection.
 * 5. Advanced options: "Require every referenced file" (default ON) and
 *    "Case-sensitive filename matching" (default ON).
 * 6. User chooses "Fix paths and create copy".
 * 7. Backend calls existing `convert_collection()`.
 * 8. Result is shown: success, missing references, ambiguous references,
 *    strict-mode blocked result, or safe error.
 *
 * Security:
 * - The renderer never receives raw absolute paths — only opaque selection
 *   IDs and safe display labels.
 * - Conflicting actions are disabled while scanning/converting.
 * - The original scene collection is never modified.
 */

import React from "react";
import type {
  DetectedCollection,
  ConvertResult,
} from "../types/api";
import { useTheme } from "./theme";

/** Workflow steps for the stepper. */
type Step = "folder" | "scan" | "collection" | "convert" | "result";

/** Safe error returned from the backend or IPC layer. */
interface SafeError {
  code: string;
  message: string;
}

/**
 * Import page component.
 *
 * Manages the full Fix Scene Collection Paths workflow state and renders
 * the appropriate step content.
 */
export function ImportPage(): React.ReactElement {
  const { palette } = useTheme();
  const [step, setStep] = React.useState<Step>("folder");
  const [isBusy, setIsBusy] = React.useState(false);
  const [error, setError] = React.useState<SafeError | null>(null);

  // Selection state — holds the opaque selection ID only.
  const [selectionId, setSelectionId] = React.useState<string | null>(null);
  const [folderLabel, setFolderLabel] = React.useState<string>("");

  // Scan state.
  const [collections, setCollections] = React.useState<DetectedCollection[]>([]);

  // Collection selection state.
  const [selectedCollectionIndex, setSelectedCollectionIndex] = React.useState<number | null>(null);
  const [collectionLabel, setCollectionLabel] = React.useState<string>("");

  // Options — defaults match AppSettings: strict_validation=True,
  // case_sensitive_matching=True.
  const [strict, setStrict] = React.useState(true);
  const [caseSensitive, setCaseSensitive] = React.useState(true);

  // Result state.
  const [result, setResult] = React.useState<ConvertResult | null>(null);

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
        handleError("Backend is not available. Start the application in development mode.");
        return;
      }
      const data = await api.chooseFolder("");
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
      const data = await api.scanCollections(selectionId);
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

  async function handleChooseCollection(index: number): Promise<void> {
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
      const data = await api.chooseCollection(selectionId, index);
      setSelectedCollectionIndex(index);
      setCollectionLabel(data.collection_label);
      setStep("convert");
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
  // Step 4: Convert
  // -----------------------------------------------------------------------

  async function handleConvert(): Promise<void> {
    if (!selectionId) {
      handleError("No folder selected.");
      return;
    }
    if (selectedCollectionIndex === null) {
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
      const data = await api.convertCollection(
        selectionId,
        strict,
        caseSensitive
      );
      setResult(data);
      setStep("result");
      // Clear the selection ID since it's been consumed.
      setSelectionId(null);
      stopBusy();
    } catch (err) {
      handleError(
        err instanceof Error
          ? err.message
          : "Could not convert the collection. Please try again."
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
    setSelectedCollectionIndex(null);
    setCollectionLabel("");
    setStrict(true);
    setCaseSensitive(true);
    setResult(null);
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
      { id: "convert", label: "Fix Paths" },
      { id: "result", label: "Result" },
    ];
    return (
      <nav
        className="import-stepper"
        aria-label="Import workflow steps"
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
              (step === "convert" && s.id !== "result") ||
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
        data-testid="import-error"
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
        data-testid="import-busy"
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
      aria-labelledby="import-title"
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
      <h1 id="import-title" className="import-title">
        Fix Scene Collection Paths
      </h1>
      <p className="import-description">
        Import an extracted overlay folder, select a scene collection, and
        create a portable copy with fixed file paths. The original scene
        collection is never modified.
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
              convert.
            </p>
            {collections.length > 0 ? (
              <ul className="collection-list" data-testid="collection-list">
                {collections.map((col) => (
                  <li key={col.index}>
                    <button
                      type="button"
                      className="collection-button"
                      onClick={() => handleChooseCollection(col.index)}
                      disabled={isBusy}
                      data-testid={`collection-${col.index}`}
                    >
                      <span className="collection-label">{col.label}</span>
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

        {step === "convert" && (
          <div className="step-convert">
            <div className="convert-info">
              <p>
                <strong>Folder:</strong> {folderLabel}
              </p>
              <p>
                <strong>Collection:</strong> {collectionLabel}
              </p>
            </div>

            <fieldset className="options-fieldset" data-testid="advanced-options">
              <legend className="options-legend">Advanced Options</legend>

              <label className="option-row">
                <input
                  type="checkbox"
                  className="option-checkbox"
                  checked={strict}
                  onChange={(e) => setStrict(e.target.checked)}
                  disabled={isBusy}
                  data-testid="strict-checkbox"
                />
                <span className="option-label">
                  Require every referenced file
                </span>
                <span className="option-description">
                  (strict mode — blocks output if any file is missing)
                </span>
              </label>

              <label className="option-row">
                <input
                  type="checkbox"
                  className="option-checkbox"
                  checked={caseSensitive}
                  onChange={(e) => setCaseSensitive(e.target.checked)}
                  disabled={isBusy}
                  data-testid="case-sensitive-checkbox"
                />
                <span className="option-label">
                  Case-sensitive filename matching
                </span>
                <span className="option-description">
                  (match file names exactly, including case)
                </span>
              </label>
            </fieldset>

            <div className="convert-actions">
              <button
                type="button"
                className="import-button-primary"
                onClick={handleConvert}
                disabled={isBusy}
                data-testid="fix-paths-button"
              >
                Fix Paths and Create Copy
              </button>
              <button
                type="button"
                className="import-button-secondary"
                onClick={() => setStep("collection")}
                disabled={isBusy}
                data-testid="back-to-collection"
              >
                Back
              </button>
            </div>

            <p className="original-notice">
              <strong>Note:</strong> The original scene collection file will
              never be modified. A new copy is created alongside it.
            </p>
          </div>
        )}

        {step === "result" && result && (
          <div className="step-result" data-testid="import-result">
            {result.success ? (
              <div className="result-success" data-testid="result-success">
                <h2 className="result-title">✓ Conversion Complete</h2>
                <dl className="result-details">
                  <div className="result-row">
                    <dt>Created copy</dt>
                    <dd>{result.output_filename ?? "—"}</dd>
                  </div>
                  <div className="result-row">
                    <dt>Files changed</dt>
                    <dd>{result.changed}</dd>
                  </div>
                  <div className="result-row">
                    <dt>Files unchanged</dt>
                    <dd>{result.unchanged}</dd>
                  </div>
                  <div className="result-row">
                    <dt>Indexed files</dt>
                    <dd>{result.indexed_files}</dd>
                  </div>
                  <div className="result-row">
                    <dt>Candidate references</dt>
                    <dd>{result.candidate_paths}</dd>
                  </div>
                </dl>
              </div>
            ) : (
              <div className="result-blocked" data-testid="result-blocked">
                <h2 className="result-title">✗ Conversion Blocked</h2>
                {result.error && (
                  <p className="result-error-message">{result.error}</p>
                )}
                {result.missing.length > 0 && (
                  <div className="result-section">
                    <h3>Missing References</h3>
                    <ul className="missing-list">
                      {result.missing.map((ref, i) => (
                        <li key={`missing-${i}`}>{ref}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {result.ambiguous.length > 0 && (
                  <div className="result-section">
                    <h3>Ambiguous References</h3>
                    {result.ambiguous.map((match, i) => (
                      <div key={`ambiguous-${i}`} className="ambiguous-item">
                        <p className="ambiguous-source">{match.source_name}</p>
                        <p className="ambiguous-original">{match.original_path}</p>
                        <ul className="candidate-list">
                          {match.candidates.map((c, j) => (
                            <li key={`candidate-${i}-${j}`}>{c}</li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                )}
                {!result.error &&
                  result.missing.length === 0 &&
                  result.ambiguous.length === 0 && (
                    <p className="result-no-details">
                      The conversion was blocked. Please review your options
                      and try again.
                    </p>
                  )}
              </div>
            )}

            <button
              type="button"
              className="import-button-secondary"
              onClick={handleReset}
              data-testid="start-over-button"
            >
              Start Over
            </button>
          </div>
        )}
      </div>

      {renderBusyOverlay()}
    </section>
  );
}
