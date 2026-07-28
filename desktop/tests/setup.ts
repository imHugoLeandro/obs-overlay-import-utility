/**
 * Test setup for Vitest.
 *
 * Provides a mock `window.electronAPI` so the renderer tests can run
 * in a jsdom environment without a real Electron process.
 *
 * Also polyfills `window.matchMedia` for jsdom, which does not
 * implement it natively.
 */

import { vi } from "vitest";
import "@testing-library/jest-dom";

// Polyfill window.matchMedia for jsdom.
// jsdom does not implement matchMedia, so we provide a minimal mock.
const matchMediaMock = vi.fn().mockImplementation((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: vi.fn(),
  removeListener: vi.fn(),
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  dispatchEvent: vi.fn(),
}));

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: matchMediaMock,
});

// Mock the electronAPI that the preload script exposes via contextBridge.
const mockElectronAPI = {
  health: vi.fn(),
  appInfo: vi.fn(),
  chooseOverlayFolder: vi.fn(),
  chooseStreamlabsOverlay: vi.fn(),
  chooseAutomaticFolder: vi.fn(),
  scanCollections: vi.fn(),
  chooseCollection: vi.fn(),
  convertCollection: vi.fn(),
  importStreamlabs: vi.fn(),
  automaticImport: vi.fn(),
  deviceRequirements: vi.fn(),
  deviceCandidates: vi.fn(),
  applyDeviceChoices: vi.fn(),
  obsRunning: vi.fn(),
  activateCollection: vi.fn(),
  listExportCollections: vi.fn(),
  chooseExportDestination: vi.fn(),
  buildExportPlan: vi.fn(),
  exportInventory: vi.fn(),
  confirmExport: vi.fn(),
};

// Assign to window so the renderer can access it.
Object.defineProperty(window, "electronAPI", {
  value: mockElectronAPI,
  writable: true,
  configurable: true,
});

// Export for use in individual tests.
export { mockElectronAPI };
