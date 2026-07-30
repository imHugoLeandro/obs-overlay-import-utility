import { IPC_CHANNELS } from "../../shared/ipcChannels";

export interface SelectionHandlerDependencies {
  ipcMain: { handle(channel: string, handler: SelectionHandler): void };
  dialog: { showOpenDialog(window: unknown, options: Record<string, unknown>): Promise<{ canceled: boolean; filePaths: string[] }> };
  getMainWindow(): unknown;
  isValidSender(sender: { getURL(): string }): boolean;
  isValidOrigin(url: string): boolean;
  canonicalizeDirectory(value: string): string | null;
  importStore: {
    createFolderSelection(path: string, label: string): string;
    chooseCollection(selectionId: string, collectionId: string): void;
    getCollectionLabel(selectionId: string): string;
  };
}

export type SelectionHandler = (event: { sender: { getURL(): string } }, payload?: unknown) => Promise<unknown>;

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function authorize(deps: SelectionHandlerDependencies, event: { sender: { getURL(): string } }): void {
  if (!deps.isValidSender(event.sender) || !deps.isValidOrigin(event.sender.getURL())) {
    throw new Error("Unauthorized sender");
  }
}

/**
 * Registers the local selection operations. These handlers deliberately do
 * not consult the backend-command registry: dialogs and in-memory selection
 * state never cross the Python transport boundary.
 */
export function registerSelectionHandlers(deps: SelectionHandlerDependencies): void {
  deps.ipcMain.handle(IPC_CHANNELS.chooseOverlayFolder, async (event) => {
    authorize(deps, event);
    const result = await deps.dialog.showOpenDialog(deps.getMainWindow(), {
      title: "Choose an extracted overlay folder",
      properties: ["openDirectory", "dontAddToRecent", "createDirectory"],
      buttonLabel: "Select Overlay Folder",
    });
    if (result.canceled || result.filePaths.length === 0) {
      throw new Error("No folder selected");
    }
    const folderPath = deps.canonicalizeDirectory(result.filePaths[0]);
    if (!folderPath) {
      throw new Error("The selected path is not a directory.");
    }
    const folderLabel = folderPath.split(/[\\/]/).pop() || folderPath;
    return {
      selection_id: deps.importStore.createFolderSelection(folderPath, folderLabel),
      folder_label: folderLabel,
    };
  });

  deps.ipcMain.handle(IPC_CHANNELS.chooseCollection, async (event, params) => {
    authorize(deps, event);
    if (!params || typeof params !== "object" || Array.isArray(params)) {
      throw new Error("Invalid selection_id");
    }
    const payload = params as Record<string, unknown>;
    if (!isNonEmptyString(payload.selection_id)) {
      throw new Error("Invalid selection_id");
    }
    if (!isNonEmptyString(payload.collection_id)) {
      throw new Error("Invalid collection_id");
    }
    deps.importStore.chooseCollection(payload.selection_id, payload.collection_id);
    return {
      selection_id: payload.selection_id,
      collection_label: deps.importStore.getCollectionLabel(payload.selection_id),
    };
  });
}
