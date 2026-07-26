/**
 * App component — the foundation React shell.
 *
 * Displays backend health and application version.
 * This is a foundation only; the real Import, Export, Resizer, and Settings
 * pages are not implemented yet.
 */

import React, { useEffect, useState } from "react";
import type { AppInfoData, HealthData } from "../types/api";
import "./App.css";

type Status = "loading" | "ok" | "error";

interface BackendState {
  health: HealthData | null;
  appInfo: AppInfoData | null;
  healthStatus: Status;
  appInfoStatus: Status;
  error: string | null;
}

function App(): React.ReactElement {
  const [state, setState] = useState<BackendState>({
    health: null,
    appInfo: null,
    healthStatus: "loading",
    appInfoStatus: "loading",
    error: null,
  });

  useEffect(() => {
    // Query the backend for health and app_info.
    // The electronAPI is exposed via contextBridge in the preload script.
    // In a pure browser environment (tests), we mock it.
    const api = window.electronAPI;

    if (!api) {
      setState((s) => ({
        ...s,
        healthStatus: "error",
        appInfoStatus: "error",
        error: "electronAPI is not available",
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
          }));
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setState((s) => ({
            ...s,
            healthStatus: "error",
            error: err.message,
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
      .catch((err) => {
        if (!cancelled) {
          setState((s) => ({
            ...s,
            appInfoStatus: "error",
            error: err.message,
          }));
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-title">OBS Overlay Import Utility</h1>
        <p className="app-subtitle">Electron + React foundation</p>
      </header>

      <main className="app-main">
        <section className="card">
          <h2>Backend Health</h2>
          {state.healthStatus === "loading" && (
            <p className="status-loading">Checking backend status…</p>
          )}
          {state.healthStatus === "ok" && state.health && (
            <dl className="info-list">
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
            <p className="status-error">
              {state.error ?? "Failed to check backend health."}
            </p>
          )}
        </section>

        <section className="card">
          <h2>Application Info</h2>
          {state.appInfoStatus === "loading" && (
            <p className="status-loading">Loading application info…</p>
          )}
          {state.appInfoStatus === "ok" && state.appInfo && (
            <dl className="info-list">
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
            <p className="status-error">
              {state.error ?? "Failed to load application info."}
            </p>
          )}
        </section>
      </main>

      <footer className="app-footer">
        <p>
          Foundation stage — Import, Export, Resizer, and Settings pages
          are not yet implemented.
        </p>
      </footer>
    </div>
  );
}

export default App;
