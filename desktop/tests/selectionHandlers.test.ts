import { describe, expect, it, vi } from "vitest";
import { IPC_CHANNELS } from "../src/main/contracts/channels";
import { registerSelectionHandlers } from "../src/main/ipc/selectionHandlers";

type Handler = (event: { sender: { getURL(): string } }, payload?: unknown) => Promise<unknown>;

function registeredHandlers() {
  const handlers = new Map<string, Handler>();
  const ipcMain = { handle: vi.fn((channel: string, handler: Handler) => handlers.set(channel, handler)) };
  const dialog = { showOpenDialog: vi.fn() };
  const store = {
    createFolderSelection: vi.fn(() => "selection-1"),
    chooseCollection: vi.fn(),
    getCollectionLabel: vi.fn(() => "Collection One"),
  };
  registerSelectionHandlers({
    ipcMain,
    dialog,
    getMainWindow: () => ({}) as never,
    isValidSender: (sender) => sender.getURL() === "app://allowed",
    isValidOrigin: (url) => url === "app://allowed",
    canonicalizeDirectory: (value) => value === "C:\\overlay" ? value : null,
    importStore: store,
  });
  return { handlers, dialog, store };
}

describe("selection IPC handlers", () => {
  it("chooseOverlayFolder reaches the native folder dialog and retains only an opaque selection", async () => {
    const { handlers, dialog, store } = registeredHandlers();
    dialog.showOpenDialog.mockResolvedValue({ canceled: false, filePaths: ["C:\\overlay"] });

    await expect(handlers.get(IPC_CHANNELS.chooseOverlayFolder)!({ sender: { getURL: () => "app://allowed" } })).resolves.toEqual({
      selection_id: "selection-1",
      folder_label: "overlay",
    });
    expect(dialog.showOpenDialog).toHaveBeenCalledOnce();
    expect(store.createFolderSelection).toHaveBeenCalledWith("C:\\overlay", "overlay");
  });

  it("chooseCollection reaches the selection store without a backend command", async () => {
    const { handlers, store } = registeredHandlers();
    await expect(handlers.get(IPC_CHANNELS.chooseCollection)!({ sender: { getURL: () => "app://allowed" } }, {
      selection_id: "selection-1", collection_id: "collection-1",
    })).resolves.toEqual({ selection_id: "selection-1", collection_label: "Collection One" });
    expect(store.chooseCollection).toHaveBeenCalledWith("selection-1", "collection-1");
  });

  it("rejects invalid senders and invalid payloads before local operations", async () => {
    const { handlers, dialog, store } = registeredHandlers();
    await expect(handlers.get(IPC_CHANNELS.chooseOverlayFolder)!({ sender: { getURL: () => "https://evil.invalid" } })).rejects.toThrow("Unauthorized sender");
    await expect(handlers.get(IPC_CHANNELS.chooseCollection)!({ sender: { getURL: () => "app://allowed" } }, { selection_id: "", collection_id: "collection-1" })).rejects.toThrow("Invalid selection_id");
    expect(dialog.showOpenDialog).not.toHaveBeenCalled();
    expect(store.chooseCollection).not.toHaveBeenCalled();
  });
});
