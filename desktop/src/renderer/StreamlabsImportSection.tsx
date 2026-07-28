/**
 * Streamlabs Import Section — Import Streamlabs Scene File workflow.
 *
 * Native .overlay dialog, busy/result/error states, creates opaque installation_id.
 */

import React from "react";
import type { StreamlabsImportResult } from "../types/api";
import type { Palette } from "./theme";

interface Props {
  palette: Palette;
}

export function StreamlabsImportSection({ palette }: Props): React.ReactElement {
  const api = window.electronAPI;
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<StreamlabsImportResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [installationId, setInstallationId] = React.useState<string | null>(null);

  const handleChooseStreamlabsOverlay = async (): Promise<void> => {
    if (!api) return;
    setBusy(true);
    setError(null);
    setResult(null);
    setInstallationId(null);
    try {
      const selection = await api.chooseStreamlabsOverlay();
      const res = await api.importStreamlabs(selection.selection_id);
      setResult(res);
      if (res.success && res.installation_id) {
        setInstallationId(res.installation_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="workflow-section" style={{ "--section-bg": palette.surface } as React.CSSProperties}>
      <h2 className="workflow-title">Import Streamlabs Scene File</h2>
      <p className="workflow-description">
        Import a Streamlabs Desktop .overlay archive. The original file is never modified.
      </p>

      <button
        type="button"
        className="import-button-primary"
        onClick={handleChooseStreamlabsOverlay}
        disabled={busy}
        data-testid="choose-streamlabs-overlay-button"
      >
        {busy ? "Importing\u2026" : "Choose .overlay File"}
      </button>

      {result && result.success && (
        <div className="result-success" data-testid="streamlabs-result">
          <h3>✓ Import Complete</h3>
          <dl className="result-details">
            <div className="result-row"><dt>Collection</dt><dd>{result.collection_name}</dd></div>
            <div className="result-row"><dt>Sources imported</dt><dd>{result.imported_sources}</dd></div>
            <div className="result-row"><dt>Canvas</dt><dd>{result.canvas_width} &times; {result.canvas_height}</dd></div>
            {result.profile_name && <div className="result-row"><dt>Profile</dt><dd>{result.profile_name}</dd></div>}
          </dl>
          {result.skipped_sources.length > 0 && (
            <div className="workflow-warning">
              <h4>Skipped sources ({result.skipped_sources.length})</h4>
              <ul>{result.skipped_sources.map((s, i) => <li key={i}>{s}</li>)}</ul>
            </div>
          )}
        </div>
      )}

      {result && !result.success && result.error && (
        <div className="result-blocked" data-testid="streamlabs-error">
          <p className="result-error-message">{result.error}</p>
        </div>
      )}

      {error && (
        <div className="import-error" role="alert" data-testid="streamlabs-import-error">
          <span className="error-message">{error}</span>
        </div>
      )}

      {busy && <div className="busy-overlay" data-testid="streamlabs-busy"><div className="busy-spinner" /><p>Importing\u2026</p></div>}
    </section>
  );
}