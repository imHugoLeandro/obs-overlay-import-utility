/**
 * Tests for the ExportPage — collection selection, plan building, and
 * export confirmation with opaque IDs only.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExportPage } from "../src/renderer/ExportPage";
import { mockElectronAPI } from "./setup";

describe("ExportPage — Collection List", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the collection list on open", () => {
    render(<ExportPage />);
    expect(screen.getByText("Export Overlay")).toBeInTheDocument();
    expect(screen.getByTestId("refresh-collections-button")).toBeInTheDocument();
  });

  it("loads and displays collections on refresh", async () => {
    mockElectronAPI.listExportCollections.mockResolvedValue({
      collections: [
        { collectionId: "col-1", label: "Current" },
        { collectionId: "col-2", label: "Backup" },
      ],
      count: 2,
    });

    render(<ExportPage />);
    await userEvent.click(screen.getByTestId("refresh-collections-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-1")).toBeInTheDocument();
    });
    expect(screen.getByTestId("collection-col-2")).toBeInTheDocument();
  });

  it("collection selection stores only collection_id", async () => {
    mockElectronAPI.listExportCollections.mockResolvedValue({
      collections: [{ collectionId: "col-1", label: "Current" }],
      count: 1,
    });

    render(<ExportPage />);
    await userEvent.click(screen.getByTestId("refresh-collections-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-1")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByTestId("collection-col-1"));

    // Should transition to destination selection step.
    await waitFor(() => {
      expect(screen.getByTestId("choose-export-destination")).toBeInTheDocument();
    });
  });
});

describe("ExportPage — Destination and Plan", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("destination selection returns opaque destination_id", async () => {
    mockElectronAPI.listExportCollections.mockResolvedValue({
      collections: [{ collectionId: "col-1", label: "Current" }],
      count: 1,
    });
    mockElectronAPI.chooseExportDestination.mockResolvedValue({
      destination_id: "dest-123",
      destination_label: "exports",
    });

    render(<ExportPage />);
    await userEvent.click(screen.getByTestId("refresh-collections-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-1")).toBeInTheDocument();
    });
    await userEvent.click(screen.getByTestId("collection-col-1"));

    await waitFor(() => {
      expect(screen.getByTestId("choose-export-destination")).toBeInTheDocument();
    });
    await userEvent.click(screen.getByTestId("choose-export-destination"));

    await waitFor(() => {
      expect(screen.getByTestId("export-mode-selection")).toBeInTheDocument();
    });
  });

  it("folder mode builds plan with opaque IDs", async () => {
    mockElectronAPI.listExportCollections.mockResolvedValue({
      collections: [{ collectionId: "col-1", label: "Current" }],
      count: 1,
    });
    mockElectronAPI.chooseExportDestination.mockResolvedValue({
      destination_id: "dest-123",
      destination_label: "exports",
    });
    mockElectronAPI.buildExportPlan.mockResolvedValue({
      plan_id: "plan-123",
      collection_label: "Current",
      collection_stem: "Current",
      compressed: false,
      source_references: 10,
      total_bytes: 512000,
      scene_count: 3,
      source_count: 5,
      browser_files: 2,
      canvas_width: 1920,
      canvas_height: 1080,
      missing_references: ["missing.png"],
      dependency_report: { fonts: [], devices: [], remote_resources: [], plugin_source_ids: [], plugin_filter_ids: [] },
      items: [],
    });

    render(<ExportPage />);
    await userEvent.click(screen.getByTestId("refresh-collections-button"));
    await waitFor(() => expect(screen.getByTestId("collection-col-1")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("collection-col-1"));
    await waitFor(() => expect(screen.getByTestId("choose-export-destination")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("choose-export-destination"));
    await waitFor(() => expect(screen.getByTestId("export-mode-selection")).toBeInTheDocument());

    await userEvent.click(screen.getByTestId("export-folder-mode"));

    await waitFor(() => {
      expect(screen.getByTestId("export-inventory")).toBeInTheDocument();
    });
    expect(screen.getByText("Current")).toBeInTheDocument();
    expect(screen.getByText("5.0 KB")).toBeInTheDocument();
    expect(screen.getByText("Missing References (1)")).toBeInTheDocument();
  });

  it("ZIP mode passes compressed=true", async () => {
    mockElectronAPI.listExportCollections.mockResolvedValue({
      collections: [{ collectionId: "col-1", label: "Current" }],
      count: 1,
    });
    mockElectronAPI.chooseExportDestination.mockResolvedValue({
      destination_id: "dest-123",
      destination_label: "exports",
    });
    mockElectronAPI.buildExportPlan.mockResolvedValue({
      plan_id: "plan-456",
      collection_label: "Current",
      collection_stem: "Current",
      compressed: true,
      source_references: 5,
      total_bytes: 1024,
      scene_count: 1,
      source_count: 2,
      browser_files: 0,
      canvas_width: null,
      canvas_height: null,
      missing_references: [],
      dependency_report: { fonts: [], devices: [], remote_resources: [], plugin_source_ids: [], plugin_filter_ids: [] },
      items: [],
    });

    render(<ExportPage />);
    await userEvent.click(screen.getByTestId("refresh-collections-button"));
    await waitFor(() => expect(screen.getByTestId("collection-col-1")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("collection-col-1"));
    await waitFor(() => expect(screen.getByTestId("choose-export-destination")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("choose-export-destination"));
    await waitFor(() => expect(screen.getByTestId("export-mode-selection")).toBeInTheDocument());

    await userEvent.click(screen.getByTestId("export-zip-mode"));

    await waitFor(() => {
      expect(screen.getByTestId("export-inventory")).toBeInTheDocument();
    });
    expect(mockElectronAPI.buildExportPlan).toHaveBeenCalledWith("col-1", "dest-123", true);
  });
});

describe("ExportPage — Confirm and Result", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("confirm export calls confirmExport with plan_id", async () => {
    mockElectronAPI.listExportCollections.mockResolvedValue({
      collections: [{ collectionId: "col-1", label: "Current" }],
      count: 1,
    });
    mockElectronAPI.chooseExportDestination.mockResolvedValue({
      destination_id: "dest-123",
      destination_label: "exports",
    });
    mockElectronAPI.buildExportPlan.mockResolvedValue({
      plan_id: "plan-123",
      collection_label: "Current",
      collection_stem: "Current",
      compressed: false,
      source_references: 10,
      total_bytes: 512000,
      scene_count: 3,
      source_count: 5,
      browser_files: 2,
      canvas_width: 1920,
      canvas_height: 1080,
      missing_references: [],
      dependency_report: { fonts: [], devices: [], remote_resources: [], plugin_source_ids: [], plugin_filter_ids: [] },
      items: [],
    });
    mockElectronAPI.confirmExport.mockResolvedValue({
      success: true,
      output_label: "Current_export",
      copied_files: 15,
      uncompressed_bytes: 512000,
      source_references: 10,
      skipped_references: [],
      already_executed: false,
      verification: { ok: true, errors: [] },
      error: null,
    });

    render(<ExportPage />);
    await userEvent.click(screen.getByTestId("refresh-collections-button"));
    await waitFor(() => expect(screen.getByTestId("collection-col-1")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("collection-col-1"));
    await waitFor(() => expect(screen.getByTestId("choose-export-destination")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("choose-export-destination"));
    await waitFor(() => expect(screen.getByTestId("export-mode-selection")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("export-folder-mode"));
    await waitFor(() => expect(screen.getByTestId("export-inventory")).toBeInTheDocument());

    await userEvent.click(screen.getByTestId("confirm-export-button"));

    await waitFor(() => {
      expect(screen.getByTestId("export-result")).toBeInTheDocument();
    });
    expect(mockElectronAPI.confirmExport).toHaveBeenCalledWith("plan-123");
    expect(screen.getByText("Export Complete")).toBeInTheDocument();
    expect(screen.getByText("15 files")).toBeInTheDocument();
  });

  it("expired plan error is shown", async () => {
    mockElectronAPI.listExportCollections.mockResolvedValue({
      collections: [{ collectionId: "col-1", label: "Current" }],
      count: 1,
    });
    mockElectronAPI.chooseExportDestination.mockResolvedValue({
      destination_id: "dest-123",
      destination_label: "exports",
    });
    mockElectronAPI.buildExportPlan.mockResolvedValue({
      plan_id: "plan-expired",
      collection_label: "Current",
      collection_stem: "Current",
      compressed: false,
      source_references: 0,
      total_bytes: 0,
      scene_count: 0,
      source_count: 0,
      browser_files: 0,
      canvas_width: null,
      canvas_height: null,
      missing_references: [],
      dependency_report: { fonts: [], devices: [], remote_resources: [], plugin_source_ids: [], plugin_filter_ids: [] },
      items: [],
    });
    mockElectronAPI.confirmExport.mockResolvedValue({
      success: false,
      output_label: null,
      copied_files: 0,
      uncompressed_bytes: 0,
      source_references: 0,
      skipped_references: [],
      already_executed: false,
      verification: null,
      error: "Plan has expired. Please rebuild and try again.",
    });

    render(<ExportPage />);
    await userEvent.click(screen.getByTestId("refresh-collections-button"));
    await waitFor(() => expect(screen.getByTestId("collection-col-1")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("collection-col-1"));
    await waitFor(() => expect(screen.getByTestId("choose-export-destination")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("choose-export-destination"));
    await waitFor(() => expect(screen.getByTestId("export-mode-selection")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("export-folder-mode"));
    await waitFor(() => expect(screen.getByTestId("export-inventory")).toBeInTheDocument());

    await userEvent.click(screen.getByTestId("confirm-export-button"));

    await waitFor(() => {
      expect(screen.getByTestId("export-error-state")).toBeInTheDocument();
    });
    expect(screen.getByText("Plan has expired. Please rebuild and try again.")).toBeInTheDocument();
  });
});

describe("ExportPage — No raw paths", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("no raw absolute path crosses preload into renderer", async () => {
    mockElectronAPI.listExportCollections.mockResolvedValue({
      collections: [{ collectionId: "col-1", label: "Current" }],
      count: 1,
    });

    render(<ExportPage />);
    await userEvent.click(screen.getByTestId("refresh-collections-button"));

    await waitFor(() => {
      expect(screen.getByTestId("collection-col-1")).toBeInTheDocument();
    });

    // The rendered DOM must never contain a raw absolute path.
    const pageText = document.body.textContent;
    expect(pageText).not.toMatch(/\/home\/|\/Users\/|\/opt\/|\/DATA\/|C:\\\\/);
  });
});
