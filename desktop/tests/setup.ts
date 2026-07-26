/**
 * Test setup for Vitest.
 *
 * Provides a mock `window.electronAPI` so the renderer tests can run
 * in a jsdom environment without a real Electron process.
 */

import { vi } from "vitest";
import "@testing-library/jest-dom";

// Mock the electronAPI that the preload script exposes via contextBridge.
const mockElectronAPI = {
  health: vi.fn(),
  appInfo: vi.fn(),
};

// Assign to window so the renderer can access it.
Object.defineProperty(window, "electronAPI", {
  value: mockElectronAPI,
  writable: true,
  configurable: true,
});

// Export for use in individual tests.
export { mockElectronAPI };
