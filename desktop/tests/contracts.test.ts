import { describe, expect, it } from "vitest";
import {
  BACKEND_COMMANDS,
  isBackendCommand,
} from "../src/main/contracts/backendCommands";
import { IPC_CHANNELS } from "../src/shared/ipcChannels";

import packageJson from "../package.json";

describe("desktop IPC contracts", () => {
  it("keeps Windows packaging as a single clean, explicit build pipeline", () => {
    expect(packageJson.scripts.build).toBe(
      "npm run clean && npm run build:renderer && npm run build:main && npm run build:preload"
    );
    expect(packageJson.scripts["build:main"]).toContain("tsc -p tsconfig.electron.json");
    expect(packageJson.scripts["build:preload"]).toBe("vite build --config vite.preload.config.ts");
    expect(packageJson.scripts.package).not.toContain("npm run build");
    expect(packageJson.scripts["package:all"]).toContain("npm run build");
    expect(packageJson.scripts["package:all"]).toContain("npm run verify:compiled");
    expect(packageJson.scripts["package:backend"]).not.toMatch(/(^|\s)python\s/);
    expect(packageJson.description).not.toMatch(/foundation|stage/i);
  });

  it("keeps every backend command in one typed registry", () => {
    expect(BACKEND_COMMANDS).toContain("health");
    expect(BACKEND_COMMANDS).toContain("scan_resize_collections");
    expect(BACKEND_COMMANDS).toContain("undo_resize");
    expect(isBackendCommand("choose_folder")).toBe(false);
    expect(isBackendCommand("choose_collection")).toBe(false);
  });

  it("defines fixed channels for local operations without treating them as backend commands", () => {
    expect(IPC_CHANNELS.chooseOverlayFolder).toBe("desktop:choose-overlay-folder");
    expect(IPC_CHANNELS.chooseCollection).toBe("desktop:choose-collection");
    expect(isBackendCommand(IPC_CHANNELS.chooseOverlayFolder)).toBe(false);
    expect(isBackendCommand(IPC_CHANNELS.chooseCollection)).toBe(false);
  });
});
