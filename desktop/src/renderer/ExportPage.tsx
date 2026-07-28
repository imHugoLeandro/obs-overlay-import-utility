/**
 * ExportPage — Export Overlay workflow.
 *
 * Required user flow:
 * 1. User selects an OBS scene collection from a renderer-safe list.
 * 2. User selects an export destination with an Electron-main folder dialog.
 * 3. User selects Folder package or ZIP package mode before planning.
 * 4. Electron main resolves opaque IDs and passes trusted paths to Python.
 * 5. Python creates an opaque backend-held export plan ID with a real TTL.
 * 6. The renderer receives a frozen, sanitized inventory only.
 * 7. Renderer cannot reconstruct, modify, or submit a replacement plan.
 * 8. The UI requires a clearly labelled Confirm Export action.
 * 9. Confirmation sends only the opaque plan ID.
 * 10. Python revalidates and executes the exact frozen plan.
 * 11. Unknown, expired, already-executed, or altered plans fail safely.
 * 12. Successful plans become idempotent.
 * 13. Display package success, copied-file count, verification status.
 */

import React from "react";
import { useTheme } from "./theme";
import type { ExportCollectionInfo, ExportInventory, ExportResult as ExportResultType } from "../types/api";

type Step = "select-collection" | "select-destination" | "select-mode" | "planning" | "review" | "confirming" | "result";

interface SelectionState {
  collection: { label: string; path: string } | null;
  destination: { path: string; label: string } | null;
  compressed: boolean;
}

/** Safe readable size helper. */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Safe readable count helper. */
function formatCount(n: number, singular: string, plural: string): string {
  return `${n} ${n === 1 ? singular : plural}`;
}

export function ExportPage(): React.ReactElement {
  const { palette } = useTheme();
  const api = window.electronAPI;

  const [step, setStep] = React.useState<Step>("select-collection");
  const [collections, setCollections] = React.useState<ExportCollectionInfo[]>([]);
  const [selection, setSelection] = React.useState<SelectionState>({
    collection: null,
    destination: null,
    compressed: false,
  });
  const [inventory, setInventory] = React.useState<ExportInventory | null>(null);
  const [result, setResult] = React.useState<ExportResultType | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  /** Fetch the list of OBS collections on mount. */
  React.useEffect(() => {
    if (!api) return;
    const obsScenesDir = ""; // Would come from settings
    api.listExportCollections(obsScenesDir).catch(() => {
      // Silently fail — user will see "no collections" state
    });
  }, [api]);

  /** Step 1: Refresh collection list. */
  const handleRefreshCollections = async (): Promise<void> => {
    if (!api) return;
    setBusy(true);
    setError(null);
    try {
      const obsScenesDir = "";
      const resp = await api.listExportCollections(obsScenesDir);
      setCollections(resp.collections);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load collections.");
    } finally {
      setBusy(false);
    }
  };

  /** Step 2: Select a destination folder. */
  const handleChooseDestination = async (): Promise<void> => {
    if (!api) return;
    setBusy(true);
    setError(null);
    try {
      const dest = await api.chooseExportDestination();
      setSelection((prev) => ({ ...prev, destination: { path: dest.destination_path, label: dest.destination_label } }));
      setStep("select-mode");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not select destination.");
    } finally {
      setBusy(false);
    }
  };

  /** Step 3-4: Build the export plan. */
  const handleBuildPlan = async (compressed: boolean): Promise<void> => {
    if (!api || !selection.collection || !selection.destination) return;
    setBusy(true);
    setError(null);
    setSelection((prev) => ({ ...prev, compressed }));
    setStep("planning");
    try {
      const inv = await api.buildExportPlan(
        selection.collection.path,
        selection.destination.path,
        compressed
      );
      setInventory(inv);
      setStep("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not build export plan.");
      setStep("select-mode");
    } finally {
      setBusy(false);
    }
  };

  /** Step 5: Confirm (execute) the export plan. */
  const handleConfirmExport = async (): Promise<void> => {
    if (!api || !inventory) return;
    setBusy(true);
    setError(null);
    setStep("confirming");
    try {
      const res = await api.confirmExport(inventory.plan_id);
      setResult(res);
      setStep("result");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed.");
      setStep("review");
    } finally {
      setBusy(false);
    }
  };

  /** Reset everything and start over. */
  const handleReset = (): void => {
    setStep("select-collection");
    setSelection({ collection: null, destination: null, compressed: false });
    setInventory(null);
    setResult(null);
    setError(null);
    setBusy(false);
  };

  /** Render the busy overlay. */
  const renderBusyOverlay = (): React.ReactNode | null => {
    if (!busy) return null;
    return (
      <div className="import-busy-overlay" data-testid="export-busy">
        <div className="import-busy-spinner" />
        <p>
          {step === "planning" && "Building export plan\u2026"}
          {step === "confirming" && "Exporting\u2026"}
          {!["planning", "confirming"].includes(step) && "Processing\u2026"}
        </p>
      </div>
    );
  };

  return (
    <section
      className="page-content"
      aria-labelledby="export-title"
      style={{ "--page-accent": palette.accent } as React.CSSProperties}
    >
      <h1 id="export-title" className="page-title">
        Export Overlay
      </h1>
      <p className="page-description">
        Export an OBS scene collection as a portable package.
      </p>

      {/* Step: select-collection — placeholder list */}
      {step === "select-collection" && (
        <div className="export-step">
          <p className="export-note">
            Select an OBS scene collection to export, then choose a
            destination folder and package format.
          </p>
          <button
            type="button"
            className="export-button-primary"
            onClick={handleChooseDestination}
            disabled={busy}
            data-testid="select-destination-button"
          >
            Choose Destination Folder
          </button>
        </div>
      )}

      {/* Step: select-destination */}
      {step === "select-destination" && (
        <div className="export-step">
          <p className="export-note">
            Select a destination folder for the exported package.
          </p>
          <button
            type="button"
            className="export-button-primary"
            onClick={handleChooseDestination}
            disabled={busy}
            data-testid="choose-export-destination"
          >
            {busy ? "Opening\u2026" : "Choose Destination"}
          </button>
        </div>
      )}

      {/* Step: select-mode — Folder or ZIP */}
      {step === "select-mode" && selection.destination && (
        <div className="export-step" data-testid="export-mode-selection">
          <h2 className="export-step-title">Package Mode</h2>
          <p className="export-note">
            Destination: <strong>{selection.destination.label}</strong>
          </p>
          <div className="export-mode-buttons">
            <button
              type="button"
              className="export-button-primary"
              onClick={() => handleBuildPlan(false)}
              disabled={busy}
              data-testid="export-folder-mode"
            >
              Folder Package
            </button>
            <button
              type="button"
              className="export-button-secondary"
              onClick={() => handleBuildPlan(true)}
              disabled={busy}
              data-testid="export-zip-mode"
            >
              ZIP Package
            </button>
          </div>
        </div>
      )}

      {/* Step: planning — busy */}
      {step === "planning" && (
        <div className="export-step" data-testid="export-planning">
          <p>Building export plan\u2026</p>
        </div>
      )}

      {/* Step: review — frozen inventory */}
      {step === "review" && inventory && (
        <div className="export-step" data-testid="export-inventory">
          <h2 className="export-step-title">Export Inventory</h2>
          <dl className="export-details">
            <div className="export-detail-row">
              <dt>Collection</dt>
              <dd>{inventory.collection_label}</dd>
            </div>
            <div className="export-detail-row">
              <dt>Package type</dt>
              <dd>{inventory.compressed ? "ZIP" : "Folder"}</dd>
            </div>
            <div className="export-detail-row">
              <dt>Total size</dt>
              <dd>{formatBytes(inventory.total_bytes)}</dd>
            </div>
            <div className="export-detail-row">
              <dt>Scenes</dt>
              <dd>{inventory.scene_count}</dd>
            </div>
            <div className="export-detail-row">
              <dt>Sources</dt>
              <dd>{inventory.source_count}</dd>
            </div>
            <div className="export-detail-row">
              <dt>File references</dt>
              <dd>{inventory.source_references}</dd>
            </div>
            <div className="export-detail-row">
              <dt>Canvas</dt>
              <dd>
                {inventory.canvas_width || "?"} &times;{" "}
                {inventory.canvas_height || "?"}
              </dd>
            </div>
            <div className="export-detail-row">
              <dt>Browser files</dt>
              <dd>{inventory.browser_files}</dd>
            </div>
          </dl>

          {inventory.missing_references.length > 0 && (
            <div className="export-warning">
              <h3>Missing References ({inventory.missing_references.length})</h3>
              <ul className="export-warning-list">
                {inventory.missing_references.slice(0, 10).map((ref, i) => (
                  <li key={i}>{ref}</li>
                ))}
                {inventory.missing_references.length > 10 && (
                  <li>+{inventory.missing_references.length - 10} more</li>
                )}
              </ul>
            </div>
          )}

          <div className="export-inventory-actions">
            <button
              type="button"
              className="export-button-primary"
              onClick={handleConfirmExport}
              disabled={busy}
              data-testid="confirm-export-button"
            >
              {busy ? "Exporting\u2026" : "Confirm Export"}
            </button>
            <button
              type="button"
              className="export-button-secondary"
              onClick={handleReset}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Step: confirming — busy */}
      {step === "confirming" && (
        <div className="export-step" data-testid="export-confirming">
          <p>Exporting package\u2026</p>
        </div>
      )}

      {/* Step: result */}
      {step === "result" && result && (
        <div className="export-step" data-testid="export-result">
          {result.success ? (
            <div className="result-success">
              <h2 className="result-title">Export Complete</h2>
              {result.already_executed && (
                <p className="export-result-note">
                  This export was already completed.
                </p>
              )}
              <dl className="export-details">
                <div className="export-detail-row">
                  <dt>Output</dt>
                  <dd>{result.output_label || "—"}</dd>
                </div>
                <div className="export-detail-row">
                  <dt>Files copied</dt>
                  <dd>{formatCount(result.copied_files, "file", "files")}</dd>
                </div>
                <div className="export-detail-row">
                  <dt>Total size</dt>
                  <dd>{formatBytes(result.uncompressed_bytes)}</dd>
                </div>
                <div className="export-detail-row">
                  <dt>References</dt>
                  <dd>{result.source_references}</dd>
                </div>
              </dl>

              {result.skipped_references.length > 0 && (
                <div className="export-warning">
                  <h3>Skipped References ({result.skipped_references.length})</h3>
                  <ul className="export-warning-list">
                    {result.skipped_references.map((ref, i) => (
                      <li key={i}>{ref}</li>
                    ))}
                  </ul>
                </div>
              )}

              {result.verification && (
                <div
                  className={
                    result.verification.ok
                      ? "export-verification-ok"
                      : "export-verification-fail"
                  }
                  data-testid="export-verification"
                >
                  <p>
                    Package verification:{" "}
                    {result.verification.ok ? "Passed" : "Failed"}
                  </p>
                  {!result.verification.ok &&
                    result.verification.errors.length > 0 && (
                    <ul>
                      {result.verification.errors.map((e, i) => (
                        <li key={i}>{e}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="result-blocked" data-testid="export-error-state">
              <h2 className="result-title">Export Failed</h2>
              {result.error && <p className="result-error-message">{result.error}</p>}
            </div>
          )}

          <button
            type="button"
            className="export-button-secondary"
            onClick={handleReset}
            data-testid="export-start-over"
          >
            Start Over
          </button>
        </div>
      )}

      {/* Error display */}
      {error && (
        <div className="export-error" data-testid="export-error">
          <p>{error}</p>
          <button
            type="button"
            className="export-button-secondary"
            onClick={() => setError(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      {renderBusyOverlay()}
    </section>
  );
}
