/**
 * Tests for the Import page workflows — Streamlabs, Automatic, and Device Setup.
 *
 * Tests against production code, not copied simulations.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ImportPage } from "../src/renderer/ImportPage";
import { mockElectronAPI } from "./setup";
import { ThemeProvider } from "../src/renderer/theme";

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider>{ui}</ThemeProvider>);
}

describe("ImportPage — Streamlabs Import", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockElectronAPI.health.mockResolvedValue({ status: "ok", pid: 1234, uptime_seconds: 1.5, python_version: "3.13.0" });
    mockElectronAPI.appInfo.mockResolvedValue({ name: "OBS Overlay Import Utility", version: "2.0.0" });
  });

  it("renders the Streamlabs import section", () => {
    renderWithTheme(<ImportPage />);
    expect(screen.getByText("Import Streamlabs Scene File")).toBeInTheDocument();
    expect(screen.getByTestId("choose-streamlabs-overlay-button")).toBeInTheDocument();
  });

  it("shows busy state during import", async () => {
    mockElectronAPI.chooseStreamlabsOverlay.mockImplementation(() => new Promise(() => {}));
    renderWithTheme(<ImportPage />);

    const btn = screen.getByTestId("choose-streamlabs-overlay-button");
    await userEvent.click(btn);

    expect(screen.getByTestId("streamlabs-busy")).toBeInTheDocument();
  });

  it("shows success result after import", async () => {
    mockElectronAPI.chooseStreamlabsOverlay.mockResolvedValue({ selection_id: "sel-1", folder_label: "archive.overlay" });
    mockElectronAPI.importStreamlabs.mockResolvedValue({
      success: true,
      installation_id: "inst-1",
      collection_name: "My Collection",
      canvas_width: 1920,
      canvas_height: 1080,
      imported_sources: 5,
      skipped_sources: [],
      profile_name: "Scene Collection",
      error: null,
    });
    mockElectronAPI.deviceRequirements.mockResolvedValue({ requirements: [], count: 0 });
    mockElectronAPI.deviceCandidates.mockResolvedValue({ candidates: [], count: 0 });
    mockElectronAPI.obsRunning.mockResolvedValue({ running: true });

    renderWithTheme(<ImportPage />);
    await userEvent.click(screen.getByTestId("choose-streamlabs-overlay-button"));

    await waitFor(() => {
      expect(screen.getByTestId("streamlabs-result")).toBeInTheDocument();
    });
    expect(screen.getByText("✓ Import Complete")).toBeInTheDocument();
    expect(screen.getByText("My Collection")).toBeInTheDocument();
  });

  it("shows error on import failure", async () => {
    mockElectronAPI.chooseStreamlabsOverlay.mockResolvedValue({ selection_id: "sel-1", folder_label: "archive.overlay" });
    mockElectronAPI.importStreamlabs.mockResolvedValue({
      success: false,
      installation_id: null,
      collection_name: "",
      canvas_width: 0,
      canvas_height: 0,
      imported_sources: 0,
      skipped_sources: [],
      profile_name: null,
      error: "Invalid .overlay archive",
    });

    renderWithTheme(<ImportPage />);
    await userEvent.click(screen.getByTestId("choose-streamlabs-overlay-button"));

    await waitFor(() => {
      expect(screen.getByTestId("streamlabs-error")).toBeInTheDocument();
    });
    expect(screen.getByText("Invalid .overlay archive")).toBeInTheDocument();
  });
});

describe("ImportPage — Automatic Import", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockElectronAPI.health.mockResolvedValue({ status: "ok", pid: 1234, uptime_seconds: 1.5, python_version: "3.13.0" });
    mockElectronAPI.appInfo.mockResolvedValue({ name: "OBS Overlay Import Utility", version: "2.0.0" });
  });

  it("renders the Automatic import section with strict/case defaults ON", () => {
    renderWithTheme(<ImportPage />);
    expect(screen.getByText("Automatic Scene Collection")).toBeInTheDocument();
    const strictCheckbox = screen.getByTestId("auto-strict-checkbox") as HTMLInputElement;
    const caseCheckbox = screen.getByTestId("auto-case-checkbox") as HTMLInputElement;
    expect(strictCheckbox.checked).toBe(true);
    expect(caseCheckbox.checked).toBe(true);
  });

  it("shows success result after automatic import", async () => {
    mockElectronAPI.chooseAutomaticFolder.mockResolvedValue({ selection_id: "sel-2", folder_label: "pack" });
    mockElectronAPI.automaticImport.mockResolvedValue({
      success: true,
      installation_id: "inst-2",
      kind: "obs_export",
      collection_name: "Auto Collection",
      canvas_width: 1920,
      canvas_height: 1080,
      profile_name: "Scene Collection",
      error: null,
      conversion: { success: true, output_filename: "Auto Collection.json", changed: 3, unchanged: 2, missing: [], ambiguous: [], indexed_files: 5, candidate_paths: 0 },
    });

    renderWithTheme(<ImportPage />);
    await userEvent.click(screen.getByTestId("automatic-import-button"));

    await waitFor(() => {
      expect(screen.getByTestId("auto-result")).toBeInTheDocument();
    });
    expect(screen.getByText("✓ Import Complete (obs_export)")).toBeInTheDocument();
  });

  it("shows error on automatic import failure", async () => {
    mockElectronAPI.chooseAutomaticFolder.mockResolvedValue({ selection_id: "sel-2", folder_label: "pack" });
    mockElectronAPI.automaticImport.mockResolvedValue({
      success: false,
      installation_id: null,
      kind: "unknown",
      collection_name: "",
      canvas_width: null,
      canvas_height: null,
      profile_name: null,
      error: "No supported package found",
      conversion: null,
    });

    renderWithTheme(<ImportPage />);
    await userEvent.click(screen.getByTestId("automatic-import-button"));

    await waitFor(() => {
      expect(screen.getByTestId("auto-error")).toBeInTheDocument();
    });
    expect(screen.getByText("No supported package found")).toBeInTheDocument();
  });
});

describe("ImportPage — Device Setup", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockElectronAPI.health.mockResolvedValue({ status: "ok", pid: 1234, uptime_seconds: 1.5, python_version: "3.13.0" });
    mockElectronAPI.appInfo.mockResolvedValue({ name: "OBS Overlay Import Utility", version: "2.0.0" });
  });

  it("shows Device Setup after a successful automatic import", async () => {
    mockElectronAPI.chooseAutomaticFolder.mockResolvedValue({ selection_id: "sel-2", folder_label: "pack" });
    mockElectronAPI.automaticImport.mockResolvedValue({
      success: true,
      installation_id: "inst-2",
      kind: "obs_export",
      collection_name: "Auto Collection",
      canvas_width: 1920,
      canvas_height: 1080,
      profile_name: "Scene Collection",
      error: null,
      conversion: { success: true, output_filename: "Auto Collection.json", changed: 3, unchanged: 2, missing: [], ambiguous: [], indexed_files: 5, candidate_paths: 0 },
    });
    mockElectronAPI.deviceRequirements.mockResolvedValue({ requirements: [{ key: "cam1", name: "Webcam", kind: "video_capture", source_id: "source-1" }], count: 1 });
    mockElectronAPI.deviceCandidates.mockResolvedValue({ candidates: [{ candidate_id: "cand-1", label: "Logitech C920", source_id: "source-1" }], count: 1 });
    mockElectronAPI.obsRunning.mockResolvedValue({ running: true });

    renderWithTheme(<ImportPage />);
    await userEvent.click(screen.getByTestId("automatic-import-button"));

    await waitFor(() => {
      expect(screen.getByText("Device Setup — Auto Collection")).toBeInTheDocument();
    });
    expect(screen.getByTestId("device-requirements")).toBeInTheDocument();
    expect(screen.getByTestId("apply-device-choices")).toBeInTheDocument();
  });

  it("device apply failure shows error", async () => {
    mockElectronAPI.chooseAutomaticFolder.mockResolvedValue({ selection_id: "sel-2", folder_label: "pack" });
    mockElectronAPI.automaticImport.mockResolvedValue({
      success: true,
      installation_id: "inst-2",
      kind: "obs_export",
      collection_name: "Auto Collection",
      canvas_width: 1920,
      canvas_height: 1080,
      profile_name: "Scene Collection",
      error: null,
      conversion: { success: true, output_filename: "Auto Collection.json", changed: 3, unchanged: 2, missing: [], ambiguous: [], indexed_files: 5, candidate_paths: 0 },
    });
    mockElectronAPI.deviceRequirements.mockResolvedValue({ requirements: [{ key: "cam1", name: "Webcam", kind: "video_capture", source_id: "source-1" }], count: 1 });
    mockElectronAPI.deviceCandidates.mockResolvedValue({ candidates: [], count: 0 });
    mockElectronAPI.obsRunning.mockResolvedValue({ running: true });
    mockElectronAPI.applyDeviceChoices.mockResolvedValue({ success: false, error: "OBS is running with this collection active" });

    renderWithTheme(<ImportPage />);
    await userEvent.click(screen.getByTestId("automatic-import-button"));

    await waitFor(() => {
      expect(screen.getByTestId("apply-device-choices")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByTestId("apply-device-choices"));

    await waitFor(() => {
      expect(screen.getByTestId("device-apply-error")).toBeInTheDocument();
    });
    expect(screen.getByText("OBS is running with this collection active")).toBeInTheDocument();
  });
});

describe("ImportPage — OBS Activation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockElectronAPI.health.mockResolvedValue({ status: "ok", pid: 1234, uptime_seconds: 1.5, python_version: "3.13.0" });
    mockElectronAPI.appInfo.mockResolvedValue({ name: "OBS Overlay Import Utility", version: "2.0.0" });
  });

  it("password field is cleared after submit", async () => {
    mockElectronAPI.chooseAutomaticFolder.mockResolvedValue({ selection_id: "sel-2", folder_label: "pack" });
    mockElectronAPI.automaticImport.mockResolvedValue({
      success: true,
      installation_id: "inst-2",
      kind: "obs_export",
      collection_name: "Auto Collection",
      canvas_width: 1920,
      canvas_height: 1080,
      profile_name: "Scene Collection",
      error: null,
      conversion: { success: true, output_filename: "Auto Collection.json", changed: 3, unchanged: 2, missing: [], ambiguous: [], indexed_files: 5, candidate_paths: 0 },
    });
    mockElectronAPI.deviceRequirements.mockResolvedValue({ requirements: [], count: 0 });
    mockElectronAPI.deviceCandidates.mockResolvedValue({ candidates: [], count: 0 });
    mockElectronAPI.obsRunning.mockResolvedValue({ running: true });
    mockElectronAPI.activateCollection.mockResolvedValue({ success: true, error: null });

    renderWithTheme(<ImportPage />);
    await userEvent.click(screen.getByTestId("automatic-import-button"));

    await waitFor(() => {
      expect(screen.getByTestId("obs-password-input")).toBeInTheDocument();
    });

    const pwdInput = screen.getByTestId("obs-password-input") as HTMLInputElement;
    await userEvent.type(pwdInput, "secret123");
    expect(pwdInput.value).toBe("secret123");

    await userEvent.click(screen.getByTestId("activate-obs-button"));

    await waitFor(() => {
      expect(pwdInput.value).toBe("");
    });
  });

  it("no password appears in rendered output after activation", async () => {
    mockElectronAPI.chooseAutomaticFolder.mockResolvedValue({ selection_id: "sel-2", folder_label: "pack" });
    mockElectronAPI.automaticImport.mockResolvedValue({
      success: true,
      installation_id: "inst-2",
      kind: "obs_export",
      collection_name: "Auto Collection",
      canvas_width: 1920,
      canvas_height: 1080,
      profile_name: "Scene Collection",
      error: null,
      conversion: { success: true, output_filename: "Auto Collection.json", changed: 3, unchanged: 2, missing: [], ambiguous: [], indexed_files: 5, candidate_paths: 0 },
    });
    mockElectronAPI.deviceRequirements.mockResolvedValue({ requirements: [], count: 0 });
    mockElectronAPI.deviceCandidates.mockResolvedValue({ candidates: [], count: 0 });
    mockElectronAPI.obsRunning.mockResolvedValue({ running: true });
    mockElectronAPI.activateCollection.mockResolvedValue({ success: true, error: null });

    renderWithTheme(<ImportPage />);
    await userEvent.click(screen.getByTestId("automatic-import-button"));

    await waitFor(() => {
      expect(screen.getByTestId("obs-password-input")).toBeInTheDocument();
    });

    await userEvent.type(screen.getByTestId("obs-password-input"), "secret123");
    await userEvent.click(screen.getByTestId("activate-obs-button"));

    await waitFor(() => {
      expect(screen.getByTestId("activate-success")).toBeInTheDocument();
    });

    // The password must not appear anywhere in the rendered DOM.
    const pageText = document.body.textContent;
    expect(pageText).not.toContain("secret123");
  });
});
