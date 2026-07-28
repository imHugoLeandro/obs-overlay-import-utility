/**
 * Device Setup Section — Device Setup Wizard and optional OBS activation.
 *
 * Available after a successful Streamlabs or Automatic import.
 * Uses only opaque installation_id — never raw paths.
 * Password field is cleared immediately after submit.
 */

import React from "react";
import type { DeviceRequirement, DeviceCandidate, DeviceApplyResult, ActivateResult } from "../types/api";
import type { Palette } from "./theme";

interface Props {
  palette: Palette;
  installationId: string;
  collectionName: string;
}

export function DeviceSetupSection({ palette, installationId, collectionName }: Props): React.ReactElement {
  const api = window.electronAPI;
  const [requirements, setRequirements] = React.useState<DeviceRequirement[]>([]);
  const [candidates, setCandidates] = React.useState<DeviceCandidate[]>([]);
  const [choices, setChoices] = React.useState<Record<string, string>>({});
  const [applying, setApplying] = React.useState(false);
  const [activateBusy, setActivateBusy] = React.useState(false);
  const [obsRunning, setObsRunning] = React.useState<boolean | null>(null);
  const [password, setPassword] = React.useState("");
  const [applyResult, setApplyResult] = React.useState<DeviceApplyResult | null>(null);
  const [activateResult, setActivateResult] = React.useState<ActivateResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loaded, setLoaded] = React.useState(false);

  React.useEffect(() => {
    if (!api || loaded) return;
    setLoaded(true);
    api.deviceRequirements(installationId).then((r) => {
      setRequirements(r.requirements);
      const initial: Record<string, string> = {};
      r.requirements.forEach((req) => { initial[req.key] = ""; });
      setChoices(initial);
    }).catch(() => {});
    api.deviceCandidates(installationId).then((r) => setCandidates(r.candidates)).catch(() => {});
    api.obsRunning().then((r) => setObsRunning(r.running)).catch(() => setObsRunning(false));
  }, [api, installationId, loaded]);

  const handleApply = async (): Promise<void> => {
    if (!api) return;
    setApplying(true);
    setError(null);
    setApplyResult(null);
    // Build choices dict: empty string means "no change", "disable" means disable
    const resolvedChoices: Record<string, unknown> = {};
    for (const req of requirements) {
      const choice = choices[req.key];
      if (choice === "disable") {
        resolvedChoices[req.key] = "disable";
      }
    }
    try {
      const res = await api.applyDeviceChoices(installationId, resolvedChoices);
      setApplyResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Apply failed.");
    } finally {
      setApplying(false);
    }
  };

  const handleActivate = async (): Promise<void> => {
    if (!api) return;
    setActivateBusy(true);
    setError(null);
    setActivateResult(null);
    try {
      const pwd = password || undefined;
      const res = await api.activateCollection(installationId, pwd);
      setActivateResult(res);
      // Clear password immediately after submit.
      setPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Activation failed.");
      setPassword("");
    } finally {
      setActivateBusy(false);
    }
  };

  return (
    <section className="workflow-section" style={{ "--section-bg": palette.surface } as React.CSSProperties}>
      <h2 className="workflow-title">Device Setup — {collectionName}</h2>
      <p className="workflow-description">
        Configure device sources for the imported collection.
      </p>

      {requirements.length === 0 && <p>No configurable device sources found.</p>}

      {requirements.length > 0 && (
        <div className="device-requirements" data-testid="device-requirements">
          {requirements.map((req) => (
            <div key={req.key} className="device-requirement-row">
              <span className="device-name">{req.name}</span>
              <span className="device-kind">({req.kind})</span>
              <select
                className="device-choice-select"
                value={choices[req.key] || ""}
                onChange={(e) => setChoices((prev) => ({ ...prev, [req.key]: e.target.value }))}
                disabled={applying}
                data-testid={`device-choice-${req.key}`}
              >
                <option value="">Keep as-is</option>
                <option value="disable">Disable source</option>
                {candidates
                  .filter((c) => c.source_id === req.source_id || !c.source_id)
                  .map((c) => (
                    <option key={c.candidate_id} value={c.candidate_id}>
                      {c.label}
                    </option>
                  ))}
              </select>
            </div>
          ))}
          <button type="button" className="import-button-primary" onClick={handleApply} disabled={applying} data-testid="apply-device-choices">
            {applying ? "Applying\u2026" : "Apply Device Settings"}
          </button>
        </div>
      )}

      {applyResult && applyResult.success && <p className="success-text" data-testid="device-apply-success">Device settings applied.</p>}
      {applyResult && !applyResult.success && applyResult.error && <p className="error-text" data-testid="device-apply-error">{applyResult.error}</p>}

      <hr className="workflow-divider" />

      <h3 className="workflow-subtitle">Activate in OBS</h3>
      <p className="workflow-description">
        OBS status: {obsRunning === null ? "Checking\u2026" : obsRunning ? "Running" : "Not detected"}
      </p>
      <p className="workflow-description">
        Activate the imported collection in OBS via WebSocket.
        This is an explicit optional action — never automatic.
      </p>
      <label className="option-row">
        <span className="option-label">OBS WebSocket password (if required):</span>
        <input
          type="password"
          className="password-input"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={activateBusy}
          data-testid="obs-password-input"
        />
      </label>
      <button type="button" className="import-button-primary" onClick={handleActivate} disabled={activateBusy} data-testid="activate-obs-button">
        {activateBusy ? "Activating\u2026" : "Activate in OBS"}
      </button>
      {activateResult && activateResult.success && <p className="success-text" data-testid="activate-success">Collection activated in OBS.</p>}
      {activateResult && !activateResult.success && activateResult.error && <p className="error-text" data-testid="activate-error">{activateResult.error}</p>}

      {error && <div className="import-error" role="alert"><span className="error-message">{error}</span></div>}
    </section>
  );
}