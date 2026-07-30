/**
 * Backend status display component.
 *
 * Shows health and app version from the Python backend.
 * Displays a clear, non-technical error state when the backend is
 * unavailable — no raw tracebacks or diagnostics in the renderer.
 */

import React from "react";
import type { AppInfoData, HealthData } from "../types/api";
import { useTheme } from "./theme";

type Status = "loading" | "ok" | "error";

interface BackendState {
  health: HealthData | null;
  appInfo: AppInfoData | null;
  healthStatus: Status;
  appInfoStatus: Status;
  error: string | null;
}

/**
 * Backend status card.
 * Shows health data (status, PID, uptime, Python version) and
 * application info (name, version).  On error, shows a clear
 * non-technical message.
 */
export function BackendStatus(): React.ReactElement {
  const { palette } = useTheme();
  const [state, setState] = React.useState<BackendState>({
    health: null,
    appInfo: null,
    healthStatus: "loading",
    appInfoStatus: "loading",
    error: null,
  });

  React.useEffect(() => {
    const api = window.electronAPI;

    if (!api) {
      setState((s) => ({
        ...s,
        healthStatus: "error",
        appInfoStatus: "error",
        error: "Backend is not available. Start the application in development mode.",
      }));
      return;
    }

    let cancelled = false;

    api
      .health()
      .then((data) => {
        if (!cancelled) {
          setState((s) => ({
            ...s,
            health: data,
            healthStatus: "ok",
            error: null,
          }));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState((s) => ({
            ...s,
            healthStatus: "error",
            error: "Backend is not available. Ensure OBS_OVERLAY_PYTHON is set.",
          }));
        }
      });

    api
      .appInfo()
      .then((data) => {
        if (!cancelled) {
          setState((s) => ({
            ...s,
            appInfo: data,
            appInfoStatus: "ok",
          }));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState((s) => ({
            ...s,
            appInfoStatus: "error",
          }));
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <aside
      className="backend-status"
      style={
        {
          "--status-bg": palette.surface,
          "--status-border": palette.border,
          "--status-accent": palette.accent,
          "--status-error": palette.accent,
          "--status-loading": palette.muted,
        } as React.CSSProperties
      }
    >
      <div className="status-card">
        <h2 className="status-card-title">Backend Health</h2>
        {state.healthStatus === "loading" && (
          <p className="status-loading" data-testid="health-loading">
            Checking backend status…
          </p>
        )}
        {state.healthStatus === "ok" && state.health && (
          <dl className="info-list" data-testid="health-ok">
            <div className="info-row">
              <dt>Status</dt>
              <dd>{state.health.status}</dd>
            </div>
            <div className="info-row">
              <dt>Process ID</dt>
              <dd>{state.health.pid}</dd>
            </div>
            <div className="info-row">
              <dt>Uptime</dt>
              <dd>{state.health.uptime_seconds.toFixed(3)} s</dd>
            </div>
            <div className="info-row">
              <dt>Python</dt>
              <dd>{state.health.python_version}</dd>
            </div>
          </dl>
        )}
        {state.healthStatus === "error" && (
          <p className="status-error" data-testid="health-error">
            {state.error ?? "Backend is not available."}
          </p>
        )}
      </div>

      <div className="status-card">
        <h2 className="status-card-title">Application Info</h2>
        {state.appInfoStatus === "loading" && (
          <p className="status-loading" data-testid="appinfo-loading">
            Loading application info…
          </p>
        )}
        {state.appInfoStatus === "ok" && state.appInfo && (
          <dl className="info-list" data-testid="appinfo-ok">
            <div className="info-row">
              <dt>Name</dt>
              <dd>{state.appInfo.name}</dd>
            </div>
            <div className="info-row">
              <dt>Version</dt>
              <dd>{state.appInfo.version}</dd>
            </div>
          </dl>
        )}
        {state.appInfoStatus === "error" && (
          <p className="status-error" data-testid="appinfo-error">
            Application info is not available.
          </p>
        )}
      </div>
    </aside>
  );
}
