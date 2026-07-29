/**
 * Fixed renderer-to-main IPC contract.
 *
 * This module is deliberately runtime-neutral: it has no Electron or Node
 * imports, performs no runtime access, and exports only fixed serializable
 * channel values plus their TypeScript types.
 */
export const IPC_CHANNELS = {
  health: "desktop:health",
  appInfo: "desktop:app-info",
  chooseOverlayFolder: "desktop:choose-overlay-folder",
  chooseStreamlabsOverlay: "desktop:choose-streamlabs-overlay",
  chooseAutomaticFolder: "desktop:choose-automatic-folder",
  chooseExportDestination: "desktop:choose-export-destination",
  scanCollections: "desktop:scan-collections",
  chooseCollection: "desktop:choose-collection",
  convertCollection: "desktop:convert-collection",
  importStreamlabs: "desktop:import-streamlabs",
  automaticImport: "desktop:automatic-import",
  deviceRequirements: "desktop:device-requirements",
  deviceCandidates: "desktop:device-candidates",
  applyDeviceChoices: "desktop:apply-device-choices",
  obsRunning: "desktop:obs-running",
  activateCollection: "desktop:activate-collection",
  listExportCollections: "desktop:list-export-collections",
  buildExportPlan: "desktop:build-export-plan",
  exportInventory: "desktop:export-inventory",
  confirmExport: "desktop:confirm-export",
  scanResizeCollections: "desktop:scan-resize-collections",
  chooseResizeCollection: "desktop:choose-resize-collection",
  resizeSourceChoices: "desktop:resize-source-choices",
  resizeSceneChoices: "desktop:resize-scene-choices",
  previewResize: "desktop:preview-resize",
  applyResize: "desktop:apply-resize",
  undoResize: "desktop:undo-resize",
} as const;

export type IpcChannel = (typeof IPC_CHANNELS)[keyof typeof IPC_CHANNELS];
