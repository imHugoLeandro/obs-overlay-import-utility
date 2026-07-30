/**
 * Tests for the AutoResizerPage React component.
 *
 * Tests:
 * - Initial state (folder selection step)
 * - Folder selection triggers scan and shows collections
 * - Collection selection shows scope step
 * - Scope selection (Collection, Scene, Source)
 * - Scene scope loads scene choices from a safe list (no manual text field)
 * - Preview shows valid/invalid state
 * - Apply resize calls backend with correct params
 * - Success result display with opaque undo ID (no raw backup path)
 * - Undo resize using opaque IDs only
 * - Live OBS unavailable state (note shown, no live buttons)
 * - Safe error display
 * - Actions disabled while busy
 * - No raw backup_path in renderer state or IPC args
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AutoResizerPage } from "../src/renderer/AutoResizerPage";
import { ThemeProvider } from "../src/renderer/theme";
import { mockElectronAPI } from "./setup";

function renderAutoResizerPage() {
  return render(
    <ThemeProvider initialTheme="light">
      <AutoResizerPage />
    </ThemeProvider>
  );
}

describe("AutoResizerPage", () => {
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
    // Default: scanResizeCollections returns one collection.
    mockElectronAPI.scanResizeCollections.mockResolvedValue({
      collections: [
        {
          collection_id: "col-abc",
          label: "collection.json",
          canvas_width: 1920,
          canvas_height: 1080,
          source_count: 5,
          scene_count: 2,
        },
      ],
      count: 1,
    });
    // Default: chooseResizeCollection succeeds.
    mockElectronAPI.chooseResizeCollection.mockResolvedValue({
      collection_id: "col-abc",
      label: "collection.json",
    });
    // Default: resizeSourceChoices returns two sources.
    mockElectronAPI.resizeSourceChoices.mockResolvedValue({
      choices: [
        { label: "Background (bg-uuid)", name: "Background", uuid: "bg-uuid" },
        { label: "Logo (logo-uuid)", name: "Logo", uuid: "logo-uuid" },
      ],
      count: 2,
    });
    // Default: resizeSceneChoices returns two scenes.
    mockElectronAPI.resizeSceneChoices.mockResolvedValue({
      scenes: ["Scene One", "Scene Two"],
      count: 2,
    });
    // Default: previewResize is valid.
    mockElectronAPI.previewResize.mockResolvedValue({
      valid: true,
      error: null,
      source_width: 1920,
      source_height: 1080,
      changed_items: 3,
    });
    // Default: applyResize succeeds with opaque undo ID (no backup_path).
    mockElectronAPI.applyResize.mockResolvedValue({
      success: true,
      error: null,
      changed_items: 3,
      source_width: 1920,
      source_height: 1080,
      target_width: 1280,
      target_height: 720,
      canvas_changed: true,
      undo_id: "undo-abc-123",
    });
    // Default: undoResize succeeds.
    mockElectronAPI.undoResize.mockResolvedValue({
      success: true,
      error: null,
    });
  });

  it("renders the initial folder selection state", () => {
    renderAutoResizerPage();
    expect(screen.getByRole("heading", { name: "Auto Resizer" })).toBeInTheDocument();
    expect(screen.getByTestId("choose-folder-button")).toBeInTheDocument();
    expect(screen.getByText(/original collection is backed up/i)).toBeInTheDocument();
  });

  it("shows the stepper with correct steps", () => {
    renderAutoResizerPage();
    expect(screen.getByText("Choose Folder")).toBeInTheDocument();
    expect(screen.getByText("Scan Collections")).toBeInTheDocument();
    expect(screen.getByText("Select Collection")).toBeInTheDocument();
    expect(screen.getByText("Resize Options")).toBeInTheDocument();
    expect(screen.getByText("Preview")).toBeInTheDocument();
    expect(screen.getByText("Result")).toBeInTheDocument();
  });

  it("folder selection triggers scan and shows collections", async () => {
    const user = userEvent.setup();
    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(mockElectronAPI.chooseOverlayFolder).toHaveBeenCalledTimes(1);
      expect(mockElectronAPI.chooseOverlayFolder).toHaveBeenCalledWith();
    });

    await waitFor(() => {
      expect(mockElectronAPI.scanResizeCollections).toHaveBeenCalledWith("sel-123");
    });

    await waitFor(() => {
      expect(screen.getByTestId("collection-list")).toBeInTheDocument();
    });

    expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    expect(screen.getByText("collection.json")).toBeInTheDocument();
    expect(screen.getByText("1920×1080")).toBeInTheDocument();
  });

  it("scanning shows a busy state", async () => {
    const user = userEvent.setup();
    mockElectronAPI.scanResizeCollections.mockImplementation(
      () => new Promise(() => {})
    );

    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-busy")).toBeInTheDocument();
    });
  });

  it("selecting a collection shows the scope step", async () => {
    const user = userEvent.setup();
    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(mockElectronAPI.chooseResizeCollection).toHaveBeenCalledWith(
        "sel-123",
        "col-abc"
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("resize-scope")).toBeInTheDocument();
    });

    expect(screen.getByTestId("scope-collection")).toBeInTheDocument();
    expect(screen.getByTestId("scope-scene")).toBeInTheDocument();
    expect(screen.getByTestId("scope-source")).toBeInTheDocument();
  });

  it("Collection scope is selected by default", async () => {
    const user = userEvent.setup();
    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-scope")).toBeInTheDocument();
    });

    const collectionRadio = screen.getByTestId("scope-collection") as HTMLInputElement;
    expect(collectionRadio.checked).toBe(true);
  });

  it("Scale Ratio mode is selected by default", async () => {
    const user = userEvent.setup();
    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-mode")).toBeInTheDocument();
    });

    const scaleRatioRadio = screen.getByTestId("mode-scale-ratio") as HTMLInputElement;
    expect(scaleRatioRadio.checked).toBe(true);
  });

  it("preview shows valid state when preview succeeds", async () => {
    const user = userEvent.setup();
    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-scope")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("next-to-preview"));

    await waitFor(() => {
      expect(screen.getByTestId("preview-valid")).toBeInTheDocument();
    });

    expect(screen.getByTestId("preview-valid")).toHaveTextContent("3");
  });

  it("apply resize calls backend with correct params", async () => {
    const user = userEvent.setup();
    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-scope")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("next-to-preview"));

    await waitFor(() => {
      expect(screen.getByTestId("preview-valid")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("apply-resize-button"));

    await waitFor(() => {
      expect(mockElectronAPI.applyResize).toHaveBeenCalledWith(
        "sel-123",
        "Collection",
        "Scale Ratio",
        1920,
        1080,
        undefined,
        undefined
      );
    });
  });

  it("shows success result with opaque undo ID (no raw backup path)", async () => {
    const user = userEvent.setup();
    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-scope")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("next-to-preview"));

    await waitFor(() => {
      expect(screen.getByTestId("preview-valid")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("apply-resize-button"));

    await waitFor(() => {
      expect(screen.getByTestId("result-success")).toBeInTheDocument();
    });

    expect(screen.getByTestId("result-success")).toHaveTextContent("3");
    expect(screen.getByTestId("undo-resize-button")).toBeInTheDocument();
    expect(screen.getByTestId("undo-available")).toBeInTheDocument();
  });

  it("does not expose raw backup_path in the result", async () => {
    const user = userEvent.setup();
    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-scope")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("next-to-preview"));

    await waitFor(() => {
      expect(screen.getByTestId("preview-valid")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("apply-resize-button"));

    await waitFor(() => {
      expect(screen.getByTestId("result-success")).toBeInTheDocument();
    });

    // The result page should not contain any raw path-like backup_path.
    const resultText = screen.getByTestId("result-success").textContent;
    expect(resultText).not.toContain("backup_path");
    expect(resultText).not.toContain(".obs-overlay-resizer-backups");
  });

  it("undo resize uses only opaque IDs", async () => {
    const user = userEvent.setup();
    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-scope")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("next-to-preview"));

    await waitFor(() => {
      expect(screen.getByTestId("preview-valid")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("apply-resize-button"));

    await waitFor(() => {
      expect(screen.getByTestId("result-success")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("undo-resize-button"));

    await waitFor(() => {
      expect(mockElectronAPI.undoResize).toHaveBeenCalledWith(
        "sel-123",
        "undo-abc-123"
      );
    });

    // Verify undoResize was NOT called with a backup_path.
    const undoCall = mockElectronAPI.undoResize.mock.calls[0];
    expect(undoCall[1]).not.toMatch(/backup_path|\.json|\.obs-overlay/);
  });

  it("shows live OBS unavailable state with honest note", async () => {
    const user = userEvent.setup();
    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-scope")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("next-to-preview"));

    await waitFor(() => {
      expect(screen.getByTestId("preview-valid")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("apply-resize-button"));

    await waitFor(() => {
      expect(screen.getByTestId("result-success")).toBeInTheDocument();
    });

    expect(screen.getByTestId("live-section")).toBeInTheDocument();
    expect(screen.getByText(/Live OBS resizing is not available/i)).toBeInTheDocument();
    // No live resize or undo buttons should be present.
    expect(screen.queryByTestId("live-resize-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("live-undo-button")).not.toBeInTheDocument();
  });

  it("does not expose applyLiveResize or undoLiveResize on the API", async () => {
    renderAutoResizerPage();
    // The mock API should not have these methods.
    expect((window.electronAPI as unknown as Record<string, unknown>).applyLiveResize).toBeUndefined();
    expect((window.electronAPI as unknown as Record<string, unknown>).undoLiveResize).toBeUndefined();
  });

  it("shows safe error when backend is unavailable", async () => {
    const user = userEvent.setup();
    mockElectronAPI.chooseOverlayFolder.mockRejectedValue(
      new Error("The backend is unavailable. Restart the application and try again.")
    );

    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-error")).toBeInTheDocument();
    });

    const errorText = screen.getByTestId("resize-error").textContent;
    expect(errorText).not.toContain("Traceback");
    expect(errorText).not.toContain("stack");
  });

  it("disables actions while busy", async () => {
    const user = userEvent.setup();
    mockElectronAPI.chooseOverlayFolder.mockImplementation(
      () => new Promise(() => {})
    );

    renderAutoResizerPage();

    const button = screen.getByTestId("choose-folder-button");
    await user.click(button);

    await waitFor(() => {
      expect(button).toBeDisabled();
    });
  });

  it("start over resets to folder selection", async () => {
    const user = userEvent.setup();
    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-scope")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("next-to-preview"));

    await waitFor(() => {
      expect(screen.getByTestId("preview-valid")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("apply-resize-button"));

    await waitFor(() => {
      expect(screen.getByTestId("result-success")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("start-over-button"));

    await waitFor(() => {
      expect(screen.getByTestId("choose-folder-button")).toBeInTheDocument();
    });
  });

  it("Source scope loads source choices", async () => {
    const user = userEvent.setup();
    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-scope")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("scope-source"));

    await waitFor(() => {
      expect(mockElectronAPI.resizeSourceChoices).toHaveBeenCalledWith("sel-123");
    });

    await waitFor(() => {
      expect(screen.getByTestId("source-select")).toBeInTheDocument();
    });

    const options = screen.getAllByRole("option");
    expect(options.length).toBe(3); // 1 placeholder + 2 sources
  });

  it("Scene scope loads scene choices from a safe selectable list (no manual text field)", async () => {
    const user = userEvent.setup();
    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-scope")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("scope-scene"));

    await waitFor(() => {
      expect(mockElectronAPI.resizeSceneChoices).toHaveBeenCalledWith("sel-123");
    });

    await waitFor(() => {
      expect(screen.getByTestId("scene-select")).toBeInTheDocument();
    });

    // Scene scope should use a <select>, not a manual text input.
    expect(screen.queryByTestId("scene-name-input")).not.toBeInTheDocument();

    const options = screen.getAllByRole("option");
    expect(options.length).toBe(3); // 1 placeholder + 2 scenes
    expect(screen.getByText("Scene One")).toBeInTheDocument();
    expect(screen.getByText("Scene Two")).toBeInTheDocument();
  });

  it("Scene scope requires selecting a scene before preview", async () => {
    const user = userEvent.setup();
    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-scope")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("scope-scene"));

    await waitFor(() => {
      expect(screen.getByTestId("scene-select")).toBeInTheDocument();
    });

    // Click "Preview Resize" without selecting a scene.
    await user.click(screen.getByTestId("next-to-preview"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-error")).toBeInTheDocument();
    });

    expect(screen.getByTestId("resize-error").textContent).toContain(
      "Choose a scene"
    );
  });

  it("preview shows invalid state when preview fails", async () => {
    const user = userEvent.setup();
    mockElectronAPI.previewResize.mockResolvedValue({
      valid: false,
      error: "The selected source is not used by any scene.",
      source_width: 1920,
      source_height: 1080,
      changed_items: 0,
    });

    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-scope")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("next-to-preview"));

    await waitFor(() => {
      expect(screen.getByTestId("preview-invalid")).toBeInTheDocument();
    });

    expect(screen.getByText(/not used by any scene/i)).toBeInTheDocument();
  });

  it("apply resize is disabled when preview is invalid", async () => {
    const user = userEvent.setup();
    mockElectronAPI.previewResize.mockResolvedValue({
      valid: false,
      error: "Some error",
      source_width: 1920,
      source_height: 1080,
      changed_items: 0,
    });

    renderAutoResizerPage();

    await user.click(screen.getByTestId("choose-folder-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-abc")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("collection-col-abc"));

    await waitFor(() => {
      expect(screen.getByTestId("resize-scope")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("next-to-preview"));

    await waitFor(() => {
      expect(screen.getByTestId("preview-invalid")).toBeInTheDocument();
    });

    const applyButton = screen.getByTestId("apply-resize-button");
    expect(applyButton).toBeDisabled();
  });
});
