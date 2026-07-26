/**
 * Tests for the React App component.
 *
 * Verifies that the renderer displays backend health and application version
 * data received from the typed electronAPI.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import App from "../src/renderer/App";

// The mock electronAPI is set up in tests/setup.ts.
// We import it here to control the mock return values.
import { mockElectronAPI } from "./setup";

describe("App component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the app title and subtitle", () => {
    mockElectronAPI.health.mockResolvedValue({
      status: "ok",
      pid: 1234,
      uptime_seconds: 1.5,
      python_version: "3.13.0",
    });
    mockElectronAPI.appInfo.mockResolvedValue({
      name: "OBS Overlay Import Utility",
      version: "2.0.0",
    });

    render(<App />);

    expect(screen.getByText("OBS Overlay Import Utility")).toBeInTheDocument();
    expect(screen.getByText("Electron + React foundation")).toBeInTheDocument();
  });

  it("displays loading state initially", () => {
    mockElectronAPI.health.mockImplementation(() => new Promise(() => {}));
    mockElectronAPI.appInfo.mockImplementation(() => new Promise(() => {}));

    render(<App />);

    expect(screen.getByText(/Checking backend status/i)).toBeInTheDocument();
    expect(screen.getByText(/Loading application info/i)).toBeInTheDocument();
  });

  it("displays health data after successful fetch", async () => {
    mockElectronAPI.health.mockResolvedValue({
      status: "ok",
      pid: 5678,
      uptime_seconds: 42.123,
      python_version: "3.13.5",
    });
    mockElectronAPI.appInfo.mockResolvedValue({
      name: "OBS Overlay Import Utility",
      version: "2.0.0",
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("ok")).toBeInTheDocument();
    });

    expect(screen.getByText("5678")).toBeInTheDocument();
    expect(screen.getByText("42.123 s")).toBeInTheDocument();
    expect(screen.getByText("3.13.5")).toBeInTheDocument();
  });

  it("displays app info after successful fetch", async () => {
    mockElectronAPI.health.mockResolvedValue({
      status: "ok",
      pid: 1234,
      uptime_seconds: 1.0,
      python_version: "3.13.0",
    });
    mockElectronAPI.appInfo.mockResolvedValue({
      name: "OBS Overlay Import Utility",
      version: "2.0.0",
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("OBS Overlay Import Utility")).toBeInTheDocument();
    });

    // The app name appears in both the header and the info list.
    const nameElements = screen.getAllByText("OBS Overlay Import Utility");
    expect(nameElements.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("2.0.0")).toBeInTheDocument();
  });

  it("displays error state when health check fails", async () => {
    mockElectronAPI.health.mockRejectedValue(new Error("Backend unavailable"));
    mockElectronAPI.appInfo.mockResolvedValue({
      name: "OBS Overlay Import Utility",
      version: "2.0.0",
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Backend unavailable/i)).toBeInTheDocument();
    });
  });

  it("displays error state when app_info fails", async () => {
    mockElectronAPI.health.mockResolvedValue({
      status: "ok",
      pid: 1234,
      uptime_seconds: 1.0,
      python_version: "3.13.0",
    });
    mockElectronAPI.appInfo.mockRejectedValue(new Error("Connection refused"));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Connection refused/i)).toBeInTheDocument();
    });
  });

  it("shows foundation disclaimer in footer", () => {
    mockElectronAPI.health.mockResolvedValue({
      status: "ok",
      pid: 1234,
      uptime_seconds: 1.0,
      python_version: "3.13.0",
    });
    mockElectronAPI.appInfo.mockResolvedValue({
      name: "OBS Overlay Import Utility",
      version: "2.0.0",
    });

    render(<App />);

    expect(
      screen.getByText(/Foundation stage/i)
    ).toBeInTheDocument();
  });
});
