/**
 * Automatic Import Section — Automatic Scene Collection workflow.
 *
 * Strict and case-sensitive controls default ON, creates opaque installation_id.
 */

import React from "react";
import type { AutomaticImportResult } from "../types/api";
import type { Palette } from "./theme";

interface Props {
  palette: Palette;
  onInstallationCreated: (installationId: string, collectionName: string) => void;
}

export function AutomaticImportSection({ palette, onInstallationCreated }: Props): React.ReactElement {
  const api = window.electronAPI;
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<AutomaticImportResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [strict, setStrict] = React.useState(true);
  const [caseSensitive, setCaseSensitive] = React.useState(true);

  const handleChooseFolder = async (): Promise<void> => {
    if (!api) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const selection = await api.chooseAutomaticFolder();
      const res = await api.automaticImport(selection.selection_id, strict, caseSensitive);
      setResult(res);
      if (res.success && res.installation_id) {
        onInstallationCreated(res.installation_id, res.collection_name);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="workflow-section" style={{ "--section-bg": palette.surface } as React.CSSProperties}>
      <h2 className="workflow-title">Automatic Scene Collection</h2>
      <p className="workflow-description">
        Detect and import a portable package, OBS export, or Streamlabs overlay automatically.
      </p>

      <fieldset className="options-fieldset" data-testid="auto-options">
        <legend className="options-legend">Options</legend>
        <label className="option-row">
          <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} disabled={busy} data-testid="auto-strict-checkbox" />
          <span className="option-label">Require every referenced file</span>
        </label>
        <label className="option-row">
          <input type="checkbox" checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} disabled={busy} data-testid="auto-case-checkbox" />
          <span className="option-label">Case-sensitive filename matching</span>
        </label>
      </fieldset>

      <button type="button" className="import-button-primary" onClick={handleChooseFolder} disabled={busy} data-testid="automatic-import-button">
        {busy ? "Importing\u2026" : "Choose Package Folder"}
      </button>

      {result && result.success && (
        <div className="result-success" data-testid="auto-result">
          <h3>✓ Import Complete ({result.kind})</h3>
          <dl className="result-details">
            <div className="result-row"><dt>Collection</dt><dd>{result.collection_name}</dd></div>
            <div className="result-row"><dt>Kind</dt><dd>{result.kind}</dd></div>
            {result.canvas_width && <div className="result-row"><dt>Canvas</dt><dd>{result.canvas_width} &times; {result.canvas_height}</dd></div>}
            {result.profile_name && <div className="result-row"><dt>Profile</dt><dd>{result.profile_name}</dd></div>}
          </dl>
          {result.conversion && (
            <div className="workflow-details">
              <p>Files changed: {result.conversion.changed}, unchanged: {result.conversion.unchanged}</p>
              {result.conversion.missing.length > 0 && (
                <div className="workflow-warning"><h4>Missing References</h4><ul>{result.conversion.missing.map((m, i) => <li key={i}>{m}</li>)}</ul></div>
              )}
            </div>
          )}
        </div>
      )}

      {result && !result.success && result.error && (
        <div className="result-blocked" data-testid="auto-error"><p className="result-error-message">{result.error}</p></div>
      )}

      {error && <div className="import-error" role="alert" data-testid="auto-import-error"><span className="error-message">{error}</span></div>}
      {busy && <div className="busy-overlay" data-testid="auto-busy"><div className="busy-spinner" /><p>Importing\u2026</p></div>}
    </section>
  );
}