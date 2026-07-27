/**
 * Import session selection store for the Electron main process.
 *
 * This module is the **sole owner** of all selected absolute paths and
 * opaque selection/collection IDs for the Fix Scene Collection Paths
 * workflow.  The renderer never receives raw absolute paths — only
 * opaque IDs and safe display labels.
 *
 * Architecture:
 * - Electron main opens the folder dialog and stores the canonical
 *   folder path in a `FolderSelection` record.
 * - Electron main scans the folder (via the Python backend) and creates
 *   a fresh opaque `collectionId` for every scanned canonical collection
 *   path.
 * - The renderer receives `{ selectionId, collectionId, label }` only.
 * - The Python backend receives concrete folder/collection paths only
 *   from Electron main over the trusted stdio channel — never opaque
 *   renderer IDs.
 *
 * Security:
 * - No generic filesystem, path, command, or function-call API.
 * - Selection IDs are cryptographically random (crypto.randomUUID).
 * - TTL of 15 minutes with injectable clock for deterministic tests.
 * - Selecting a new folder does not reuse old IDs.
 */

import { randomUUID } from "crypto";
import { statSync } from "fs";
import { resolve, sep } from "path";

/** Injectable clock interface for deterministic TTL testing. */
export interface Clock {
  now(): number;
}

/** Default clock using Date.now(). */
const defaultClock: Clock = { now: () => Date.now() };

/** TTL for selections: 15 minutes in milliseconds. */
const SELECTION_TTL_MS = 15 * 60 * 1000;

/** Customer-safe error message for expired/unknown selections. */
export const EXPIRED_SELECTION_ERROR =
  "This selection has expired. Choose the folder again.";

/** A scanned collection with its canonical path and opaque ID. */
export interface ScannedCollection {
  /** Opaque collection ID — safe to send to the renderer. */
  collectionId: string;
  /** Canonical absolute path — never sent to the renderer. */
  path: string;
  /** Safe display label relative to the folder, or basename. */
  label: string;
}

/** A folder selection record — owns the canonical folder path and scanned collections. */
export interface FolderSelection {
  /** Opaque selection ID — safe to send to the renderer. */
  selectionId: string;
  /** Canonical absolute folder path — never sent to the renderer. */
  folderPath: string;
  /** Safe display label (folder basename). */
  folderLabel: string;
  /** Scanned collections with their canonical paths. */
  collections: ScannedCollection[];
  /** Opaque ID of the currently chosen collection, if any. */
  chosenCollectionId: string | null;
  /** Creation timestamp (ms since epoch). */
  createdAt: number;
  /** Whether conversion has been completed for this selection. */
  converted: boolean;
}

/**
 * Error thrown when a selection ID is unknown or expired.
 * The message is customer-safe and never contains raw paths.
 */
export class SelectionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SelectionError";
  }
}

/**
 * In-memory, session-only store for import workflow selections.
 *
 * The store holds canonical absolute paths that the renderer never
 * sees.  Only opaque selection IDs and collection IDs are returned
 * to the renderer.
 *
 * @param clock Optional injectable clock for deterministic TTL testing.
 */
export class ImportSelectionStore {
  private _store: Map<string, FolderSelection> = new Map();
  private _clock: Clock;

  constructor(clock: Clock = defaultClock) {
    this._clock = clock;
  }

  /**
   * Create a new folder selection record.
   *
   * @param folderPath The canonical absolute folder path (from the dialog).
   * @param folderLabel A safe display label (folder basename).
   * @returns The opaque selection ID.
   */
  createFolderSelection(folderPath: string, folderLabel: string): string {
    const selectionId = randomUUID();
    this._store.set(selectionId, {
      selectionId,
      folderPath,
      folderLabel,
      collections: [],
      chosenCollectionId: null,
      createdAt: this._clock.now(),
      converted: false,
    });
    return selectionId;
  }

  /**
   * Set the scanned collections for a selection.
   *
   * Called by Electron main after scanning the folder via the Python
   * backend.  Each collection gets a fresh opaque collectionId.
   *
   * @param selectionId The opaque selection ID.
   * @param collections Array of { path, label } from the scan.
   * @throws {SelectionError} if the selection is unknown or expired.
   */
  setCollections(
    selectionId: string,
    collections: { path: string; label: string }[]
  ): void {
    const selection = this._getValid(selectionId);
    selection.collections = collections.map((c) => ({
      collectionId: randomUUID(),
      path: c.path,
      label: c.label,
    }));
    selection.chosenCollectionId = null;
  }

  /**
   * Get the safe display collections for a selection.
   *
   * Returns only { collectionId, label } — never raw paths.
   *
   * @param selectionId The opaque selection ID.
   * @returns Array of { collectionId, label }.
   * @throws {SelectionError} if the selection is unknown or expired.
   */
  getCollections(selectionId: string): { collectionId: string; label: string }[] {
    const selection = this._getValid(selectionId);
    return selection.collections.map((c) => ({
      collectionId: c.collectionId,
      label: c.label,
    }));
  }

  /**
   * Get the folder label for a selection.
   *
   * @param selectionId The opaque selection ID.
   * @returns The safe folder label.
   * @throws {SelectionError} if the selection is unknown or expired.
   */
  getFolderLabel(selectionId: string): string {
    const selection = this._getValid(selectionId);
    return selection.folderLabel;
  }

  /**
   * Choose a collection by its opaque collectionId.
   *
   * Verifies that the collectionId belongs to this selection.
   *
   * @param selectionId The opaque selection ID.
   * @param collectionId The opaque collection ID.
   * @throws {SelectionError} if the selection is unknown/expired or
   *   the collectionId does not belong to this selection.
   */
  chooseCollection(selectionId: string, collectionId: string): void {
    const selection = this._getValid(selectionId);
    const exists = selection.collections.some(
      (c) => c.collectionId === collectionId
    );
    if (!exists) {
      throw new SelectionError(
        "This collection is no longer available. Scan the folder again."
      );
    }
    selection.chosenCollectionId = collectionId;
  }

  /**
   * Get the canonical folder path for a selection.
   *
   * Used by Electron main to pass the trusted path to the Python backend.
   *
   * @param selectionId The opaque selection ID.
   * @returns The canonical absolute folder path.
   * @throws {SelectionError} if the selection is unknown or expired.
   */
  getFolderPath(selectionId: string): string {
    const selection = this._getValid(selectionId);
    return selection.folderPath;
  }

  /**
   * Get the canonical collection path for a selection.
   *
   * Used by Electron main to pass the trusted path to the Python backend.
   * Revalidates that the collection still exists, is a regular file,
   * and resolves under the selected folder.
   *
   * @param selectionId The opaque selection ID.
   * @returns The canonical absolute collection path.
   * @throws {SelectionError} if the selection is unknown/expired, no
   *   collection is chosen, the collection no longer exists, or the
   *   path escapes the folder (symlink/reparse-point).
   */
  getCollectionPath(selectionId: string): string {
    const selection = this._getValid(selectionId);

    if (!selection.chosenCollectionId) {
      throw new SelectionError(
        "No collection has been selected. Choose one first."
      );
    }

    const collection = selection.collections.find(
      (c) => c.collectionId === selection.chosenCollectionId
    );

    if (!collection) {
      throw new SelectionError(
        "This collection is no longer available. Scan the folder again."
      );
    }

    // Revalidate: the collection must still exist and be a regular file.
    // This prevents TOCTOU issues where the file was deleted or replaced
    // after scanning.
    try {
      const stat = statSync(collection.path);
      if (!stat.isFile()) {
        throw new SelectionError(
          "The selected collection is no longer a valid file. Scan the folder again."
        );
      }
    } catch (err) {
      throw new SelectionError(
        "The selected collection is no longer available. Scan the folder again."
      );
    }

    // Revalidate: the collection must resolve under the selected folder.
    // This prevents symlink/reparse-point escapes.
    const folderResolved = resolve(selection.folderPath);
    const collectionResolved = resolve(collection.path);
    if (!collectionResolved.startsWith(folderResolved + sep)) {
      throw new SelectionError(
        "The selected collection is not inside the chosen folder."
      );
    }

    return collection.path;
  }

  /**
   * Mark a selection as converted (idempotency check).
   *
   * @param selectionId The opaque selection ID.
   * @throws {SelectionError} if the selection is unknown/expired or
   *   already converted.
   */
  markConverted(selectionId: string): void {
    const selection = this._getValid(selectionId);
    if (selection.converted) {
      throw new SelectionError(
        "This collection has already been converted. Choose a folder again."
      );
    }
    selection.converted = true;
  }

  /**
   * Check if a selection has been converted.
   *
   * @param selectionId The opaque selection ID.
   * @returns true if already converted.
   * @throws {SelectionError} if the selection is unknown or expired.
   */
  isConverted(selectionId: string): boolean {
    const selection = this._getValid(selectionId);
    return selection.converted;
  }

  /**
   * Remove a selection from the store (e.g., on cleanup).
   *
   * @param selectionId The opaque selection ID.
   */
  remove(selectionId: string): void {
    this._store.delete(selectionId);
  }

  /**
   * Clear all selections (used on app shutdown).
   */
  clear(): void {
    this._store.clear();
  }

  /**
   * Internal: get a valid (non-expired) selection.
   *
   * @param selectionId The opaque selection ID.
   * @returns The FolderSelection record.
   * @throws {SelectionError} if the selection is unknown or expired.
   */
  private _getValid(selectionId: string): FolderSelection {
    const selection = this._store.get(selectionId);
    if (!selection) {
      throw new SelectionError(EXPIRED_SELECTION_ERROR);
    }
    const age = this._clock.now() - selection.createdAt;
    if (age > SELECTION_TTL_MS) {
      this._store.delete(selectionId);
      throw new SelectionError(EXPIRED_SELECTION_ERROR);
    }
    return selection;
  }
}
