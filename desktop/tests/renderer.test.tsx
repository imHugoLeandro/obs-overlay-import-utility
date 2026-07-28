/**
 * Tests for the React App component — Social Space shell.
 *
 * Tests:
 * - Renders the navigation sidebar with all four items
 * - Shows the Import page by default
 * - Navigating to a page shows its content
 * - Backend status shows loading, ok, and error states
 * - Theme selector is available on the Settings page
 * - No raw traceback or backend diagnostic in error state
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../src/renderer/App";
import { mockElectronAPI } from "./setup";

describe("App component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: backend is healthy.
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
  });

  it("renders the navigation sidebar with all four items", () => {
    render(<App />);
    expect(screen.getByRole("button", { name: "Import" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Auto Resizer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Settings" })).toBeInTheDocument();
  });

  it("shows the Import page content by default", () => {
    render(<App />);
    // The Import page now shows the functional Fix Scene Collection Paths workflow.
    expect(screen.getByRole("heading", { name: "Fix Scene Collection Paths" })).toBeInTheDocument();
    expect(screen.getByTestId("choose-folder-button")).toBeInTheDocument();
  });

  it("shows the Export page content (functional)", async () => {
    const user = userEvent.setup();
    mockElectronAPI.listExportCollections.mockResolvedValue({
      collections: [{ collectionId: "col-1", label: "Current" }],
      count: 1,
    });
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Export" }));

    expect(screen.getByRole("heading", { name: "Export Overlay" })).toBeInTheDocument();
    expect(screen.getByTestId("select-destination-button")).toBeInTheDocument();
  });

  it("shows placeholder content for Auto Resizer page", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Auto Resizer" }));

    expect(screen.getByRole("heading", { name: "Auto Resizer" })).toBeInTheDocument();
    expect(screen.getByText("Auto Resizer workflows are coming next.")).toBeInTheDocument();
  });

  it("shows Settings page with theme selector", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Settings" }));

    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByLabelText("Theme")).toBeInTheDocument();
  });

  it("shows loading state for backend health", () => {
    mockElectronAPI.health.mockImplementation(() => new Promise(() => {}));
    mockElectronAPI.appInfo.mockImplementation(() => new Promise(() => {}));

    render(<App />);

    expect(screen.getByTestId("health-loading")).toBeInTheDocument();
    expect(screen.getByTestId("appinfo-loading")).toBeInTheDocument();
  });

  it("shows health data after successful fetch", async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("health-ok")).toBeInTheDocument();
    });

    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.getByText("1234")).toBeInTheDocument();
    expect(screen.getByText("1.500 s")).toBeInTheDocument();
    expect(screen.getByText("3.13.0")).toBeInTheDocument();
  });

  it("shows app info after successful fetch", async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("appinfo-ok")).toBeInTheDocument();
    });

    expect(screen.getByText("OBS Overlay Import Utility")).toBeInTheDocument();
    expect(screen.getByText("2.0.0")).toBeInTheDocument();
  });

  it("shows non-technical error state when health check fails", async () => {
    mockElectronAPI.health.mockRejectedValue(new Error("Backend unavailable"));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("health-error")).toBeInTheDocument();
    });

    // The error message should be non-technical — no raw traceback.
    const errorText = screen.getByTestId("health-error").textContent;
    expect(errorText).not.toContain("Traceback");
    expect(errorText).not.toContain("stack");
    expect(errorText).not.toContain("Error: Backend unavailable");
  });

  it("shows error state when app_info fails", async () => {
    mockElectronAPI.appInfo.mockRejectedValue(new Error("Connection refused"));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("appinfo-error")).toBeInTheDocument();
    });

    // No raw traceback in the error state.
    const errorText = screen.getByTestId("appinfo-error").textContent;
    expect(errorText).not.toContain("Traceback");
    expect(errorText).not.toContain("Connection refused");
  });

  it("shows Stage 2 footer mentioning Import and Export are implemented", async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Stage 2/i)).toBeInTheDocument();
    });

    // The footer should mention that Import and Export workflows are implemented.
    const footer = screen.getByText(/Stage 2/i).closest("footer");
    expect(footer).not.toBeNull();
    expect(footer!.textContent).toContain("Import");
    expect(footer!.textContent).toContain("Export");
    expect(footer!.textContent).toContain("implemented");
  });

  it("supports keyboard navigation between pages", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Tab to the first nav button.
    await user.tab();
    expect(screen.getByRole("button", { name: "Import" })).toHaveFocus();

    // Arrow down to Export.
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("button", { name: "Export" })).toHaveFocus();

    // Enter to navigate.
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Export Overlay" })).toBeInTheDocument();
    });
  });

  it("has accessible navigation label", () => {
    render(<App />);
    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeInTheDocument();
  });
});
