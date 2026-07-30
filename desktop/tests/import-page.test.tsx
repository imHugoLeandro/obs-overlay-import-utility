/**
 * Tests for the ImportPage React component — Fix Scene Collection Paths workflow.
 *
 * Tests:
 * - Initial state (folder selection step)
 * - Folder selection (chooseOverlayFolder → scan → collection step)
 * - Scanning/busy state
 * - Detected collection selection (by collection_id)
 * - Strict and case-sensitive defaults ON
 * - Success result display
 * - Missing/ambiguous result display
 * - Safe error display
 * - Action disabled while busy
 * - chooseOverlayFolder takes no parameters
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ImportPage } from "../src/renderer/ImportPage";
import { ThemeProvider } from "../src/renderer/theme";
import { mockElectronAPI } from "./setup";

function renderImportPage() {
  return render(
    <ThemeProvider initialTheme="light">
      <ImportPage />
    </ThemeProvider>
  );
}

describe("ImportPage", () => {
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
    // Default: chooseOverlayFolder succeeds (no parameters).
    mockElectronAPI.chooseOverlayFolder.mockResolvedValue({
      selection_id: "sel-123",
      folder_label: "my-overlay",
    });
    // Default: scanCollections returns one collection with collection_id.
    mockElectronAPI.scanCollections.mockResolvedValue({
      selection_id: "sel-123",
      folder_label: "my-overlay",
      collections: [{ collection_id: "col-abc", label: "collection.json" }],
      count: 1,
    });
    // Default: chooseCollection succeeds.
    mockElectronAPI.chooseCollection.mockResolvedValue({
      selection_id: "sel-123",
      collection_label: "collection.json",
    });
    // Default: convertCollection succeeds.
    mockElectronAPI.convertCollection.mockResolvedValue({
      success: true,
      changed: 3,
      unchanged: 2,
      missing: [],
      ambiguous: [],
      indexed_files: 10,
      candidate_paths: 5,
      output_filename: "collection_ImportReady.json",
      output_path: "collection_ImportReady.json",
    });
  });

  it("renders the initial folder selection state", () => {
    renderImportPage();
    expect(screen.getByRole("heading", { name: "Fix Scene Collection Paths" })).toBeInTheDocument();
    expect(screen.getByTestId("choose-folder-button")).toBeInTheDocument();
    expect(screen.getByText(/original scene collection is never modified/i)).toBeInTheDocument();
  });

  it("shows the stepper with correct steps", () => {
    renderImportPage();
    expect(screen.getByText("Choose Folder")).toBeInTheDocument();
    expect(screen.getByText("Scan Collections")).toBeInTheDocument();
    expect(screen.getByText("Select Collection")).toBeInTheDocument();
    expect(screen.getByText("Fix Paths")).toBeInTheDocument();
    expect(screen.getByText("Result")).toBeInTheDocument();
  });

  it("folder selection triggers scan and shows collections", async () => {
    const user = userEvent.setup();
    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(mockElectronAPI.chooseOverlayFolder).toHaveBeenCalledTimes(1);
      // chooseOverlayFolder takes no parameters.
      expect(mockElectronAPI.chooseOverlayFolder).toHaveBeenCalledWith();
    });

    await waitFor(() => {
      expect(mockElectronAPI.scanCollections).toHaveBeenCalledWith("sel-123");
    });

    await waitFor(() => {
      expect(screen.getByTestId("collection-list")).toBeInTheDocument();
    });

    expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    expect(screen.getByText("collection.json")).toBeInTheDocument();
  });

  it("scanning shows a busy state", async () => {
    const user = userEvent.setup();
    // Make scanCollections hang to test busy state.
    mockElectronAPI.scanCollections.mockImplementation(
      () => new Promise(() => {})
    );

    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("import-busy")).toBeInTheDocument();
    });
  });

  it("selecting a collection shows the convert step with options", async () => {
    const user = userEvent.setup();
    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(mockElectronAPI.chooseCollection).toHaveBeenCalledWith("sel-123", "col-abc");
    });

    await waitFor(() => {
      expect(screen.getByTestId("advanced-options")).toBeInTheDocument();
    });

    expect(screen.getByTestId("fix-paths-button")).toBeInTheDocument();
    expect(screen.getByTestId("back-to-collection")).toBeInTheDocument();
  });

  it("strict option defaults to ON", async () => {
    const user = userEvent.setup();
    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("advanced-options")).toBeInTheDocument();
    });

    const strictCheckbox = screen.getByTestId("strict-checkbox") as HTMLInputElement;
    expect(strictCheckbox.checked).toBe(true);
  });

  it("case-sensitive option defaults to ON", async () => {
    const user = userEvent.setup();
    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("advanced-options")).toBeInTheDocument();
    });

    const caseCheckbox = screen.getByTestId("case-sensitive-checkbox") as HTMLInputElement;
    expect(caseCheckbox.checked).toBe(true);
  });

  it("convert calls backend with strict and case_sensitive options", async () => {
    const user = userEvent.setup();
    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("fix-paths-button")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("fix-paths-button"));

    await waitFor(() => {
      expect(mockElectronAPI.convertCollection).toHaveBeenCalledWith(
        "sel-123",
        true,
        true
      );
    });
  });

  it("convert with strict off passes false", async () => {
    const user = userEvent.setup();
    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("fix-paths-button")).toBeInTheDocument();
    });

    // Turn off strict.
    await user.click(screen.getByTestId("strict-checkbox"));

    await user.click(screen.getByTestId("fix-paths-button"));

    await waitFor(() => {
      expect(mockElectronAPI.convertCollection).toHaveBeenCalledWith(
        "sel-123",
        false,
        true
      );
    });
  });

  it("shows success result with created-copy filename, changed count, etc.", async () => {
    const user = userEvent.setup();
    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("fix-paths-button")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("fix-paths-button"));

    await waitFor(() => {
      expect(screen.getByTestId("result-success")).toBeInTheDocument();
    });

    expect(screen.getByText("collection_ImportReady.json")).toBeInTheDocument();
    // Use the result-details dl to scope the search for counts.
    const details = screen.getByTestId("result-success").querySelector(".result-details");
    expect(details).not.toBeNull();
    // changed count
    expect(details!.textContent).toContain("3");
    // unchanged count
    expect(details!.textContent).toContain("2");
    // indexed_files
    expect(details!.textContent).toContain("10");
    // candidate_paths
    expect(details!.textContent).toContain("5");
  });

  it("shows missing references in blocked result", async () => {
    const user = userEvent.setup();
    mockElectronAPI.convertCollection.mockResolvedValue({
      success: false,
      changed: 0,
      unchanged: 0,
      missing: ["Overlay source: C:\\old\\missing.png"],
      ambiguous: [],
      indexed_files: 0,
      candidate_paths: 1,
    });

    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("fix-paths-button")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("fix-paths-button"));

    await waitFor(() => {
      expect(screen.getByTestId("result-blocked")).toBeInTheDocument();
    });

    expect(screen.getByText("Missing References")).toBeInTheDocument();
    expect(screen.getByText("Overlay source: C:\\old\\missing.png")).toBeInTheDocument();
  });

  it("shows ambiguous references in blocked result", async () => {
    const user = userEvent.setup();
    mockElectronAPI.convertCollection.mockResolvedValue({
      success: false,
      changed: 0,
      unchanged: 0,
      missing: [],
      ambiguous: [
        {
          source_name: "Overlay source",
          original_path: "C:\\old\\same.png",
          candidates: ["one/same.png", "two/same.png"],
        },
      ],
      indexed_files: 2,
      candidate_paths: 1,
    });

    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("fix-paths-button")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("fix-paths-button"));

    await waitFor(() => {
      expect(screen.getByTestId("result-blocked")).toBeInTheDocument();
    });

    expect(screen.getByText("Ambiguous References")).toBeInTheDocument();
    expect(screen.getByText("Overlay source")).toBeInTheDocument();
    expect(screen.getByText("C:\\old\\same.png")).toBeInTheDocument();
    expect(screen.getByText("one/same.png")).toBeInTheDocument();
    expect(screen.getByText("two/same.png")).toBeInTheDocument();
  });

  it("shows safe error when backend is unavailable", async () => {
    const user = userEvent.setup();
    mockElectronAPI.chooseOverlayFolder.mockRejectedValue(
      new Error("The backend is unavailable. Restart the application and try again.")
    );

    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("import-error")).toBeInTheDocument();
    });

    const errorText = screen.getByTestId("import-error").textContent;
    expect(errorText).not.toContain("Traceback");
    expect(errorText).not.toContain("stack");
  });

  it("disables actions while busy", async () => {
    const user = userEvent.setup();
    // Make chooseOverlayFolder hang.
    mockElectronAPI.chooseOverlayFolder.mockImplementation(
      () => new Promise(() => {})
    );

    renderImportPage();

    const button = screen.getByTestId("choose-folder-button");
    await user.click(button);

    await waitFor(() => {
      expect(button).toBeDisabled();
    });
  });

  it("shows safe error for unknown/expired selection ID", async () => {
    const user = userEvent.setup();
    mockElectronAPI.scanCollections.mockRejectedValue(
      new Error("This selection has expired. Choose the folder again.")
    );

    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("import-error")).toBeInTheDocument();
    });

    expect(
      screen.getByText(/has expired/i)
    ).toBeInTheDocument();
  });

  it("start over resets to folder selection", async () => {
    const user = userEvent.setup();
    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("fix-paths-button")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("fix-paths-button"));

    await waitFor(() => {
      expect(screen.getByTestId("result-success")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("start-over-button"));

    await waitFor(() => {
      expect(screen.getByTestId("choose-folder-button")).toBeInTheDocument();
    });
  });

  it("shows the real collection label after choosing (not 'selected')", async () => {
    const user = userEvent.setup();
    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(mockElectronAPI.chooseCollection).toHaveBeenCalledWith("sel-123", "col-abc");
    });

    // The convert step should show the real collection label, not "selected".
    await waitFor(() => {
      expect(screen.getByTestId("fix-paths-button")).toBeInTheDocument();
    });

    // The collection label should be "collection.json" (from the mock),
    // not the hard-coded "selected" string.
    expect(screen.getByText("collection.json")).toBeInTheDocument();
  });

  it("has accessible labels and status messages", async () => {
    const user = userEvent.setup();
    renderImportPage();
    expect(screen.getByRole("heading", { name: "Fix Scene Collection Paths" })).toBeInTheDocument();

    // Navigate to the convert step to check the option labels.
    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("advanced-options")).toBeInTheDocument();
    });

    expect(screen.getByTestId("strict-checkbox")).toBeInTheDocument();
    expect(screen.getByTestId("case-sensitive-checkbox")).toBeInTheDocument();
  });

  it("shows original-not-modified notice", async () => {
    const user = userEvent.setup();
    renderImportPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("fix-paths-button")).toBeInTheDocument();
    });

    expect(screen.getByText(/original scene collection file will never be modified/i)).toBeInTheDocument();
  });
});
