/**
 * Session-only store for resize undo operations.
 *
 * Electron main is the sole owner of concrete backup paths.  When an
 * offline resize succeeds, the Python backend returns the concrete
 * `backup_path` to Electron main only.  Electron main stores that path
 * here under an opaque `undoId` and returns only the `undoId` to the
 * renderer.
 *
 * The renderer can never receive or submit a raw backup path.
 * Undo requests carry only the opaque `undoId` (and the `selectionId`
 * it was bound to), which Electron main resolves back to the concrete
 * path before forwarding it to the Python backend.
 *
 * Security:
 * - Undo IDs are cryptographically random (crypto.randomUUID).
 * - TTL of 15 minutes with injectable clock for deterministic tests.
 * - Each undoId is bound to the selectionId it was created under.
 * - Unknown, expired, or mismatched IDs are rejected.
 * - A backup can only be undone once (one-shot).
 */

import { randomUUID } from "crypto";
import { statSync, existsSync } from "fs";

/** Injectable clock interface for deterministic TTL testing. */
export interface Clock {
  now(): number;
}

/** Default clock using Date.now(). */
const defaultClock: Clock = { now: () => Date.now() };

/** TTL for undo IDs: 15 minutes in milliseconds. */
const UNDO_TTL_MS = 15 * 60 * 1000;

/** Customer-safe error message for expired/unknown undo IDs. */
export const EXPIRED_UNDO_ERROR =
  "This undo operation is no longer available. Resize the collection again to create a new backup.";

/** A single undo record — owns the concrete backup path. */
interface UndoRecord {
  /** Opaque undo ID — safe to send to the renderer. */
  undoId: string;
  /** Opaque selection ID this undo was bound to. */
  selectionId: string;
  /** Canonical absolute backup path — never sent to the renderer. */
  backupPath: string;
  /** Canonical absolute collection path — never sent to the renderer. */
  collectionPath: string;
  /** Creation timestamp (ms since epoch). */
  createdAt: number;
  /** Whether this undo has already been consumed (one-shot). */
  consumed: boolean;
}

/**
 * Error thrown when an undo ID is unknown, expired, mismatched, or
 * already consumed.  The message is customer-safe and never contains
 * raw paths.
 */
export class UndoError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UndoError";
  }
}

/**
 * In-memory, session-only store for resize undo operations.
 *
 * @param clock Optional injectable clock for deterministic TTL testing.
 */
export class ResizeUndoStore {
  private _store: Map<string, UndoRecord> = new Map();
  private _clock: Clock;

  constructor(clock: Clock = defaultClock) {
    this._clock = clock;
  }

  /**
   * Register a backup path and return an opaque undo ID.
   *
   * Called by Electron main after a successful offline resize.  The
   * concrete backup and collection paths stay in Electron main only.
   *
   * @param selectionId The opaque selection ID the resize was bound to.
   * @param collectionPath The canonical absolute collection path.
   * @param backupPath The canonical absolute backup path.
   * @returns The opaque undo ID to send to the renderer.
   */
  registerUndo(
    selectionId: string,
    collectionPath: string,
    backupPath: string
  ): string {
    const undoId = randomUUID();
    this._store.set(undoId, {
      undoId,
      selectionId,
      collectionPath,
      backupPath,
      createdAt: this._clock.now(),
      consumed: false,
    });
    return undoId;
  }

  /**
   * Resolve an undo ID to its concrete backup and collection paths.
   *
   * Validates that:
   * - The undo ID exists and has not expired.
   * - The undo ID was bound to the given selectionId.
   * - The undo has not already been consumed (one-shot).
   *
   * On success, marks the undo as consumed so it cannot be replayed.
   *
   * @param undoId The opaque undo ID from the renderer.
   * @param selectionId The opaque selection ID to match against.
   * @returns { backupPath, collectionPath } — concrete paths for the
   *   Python backend.
   * @throws {UndoError} if the undo ID is unknown, expired, mismatched,
   *   or already consumed.
   */
  resolveUndo(undoId: string, selectionId: string): {
    backupPath: string;
    collectionPath: string;
  } {
    const record = this._getValid(undoId, selectionId);

    // Mark as consumed so it cannot be replayed.
    record.consumed = true;

    // Revalidate the backup file still exists before returning the path.
    if (!existsSync(record.backupPath)) {
      throw new UndoError(EXPIRED_UNDO_ERROR);
    }
    try {
      const stat = statSync(record.backupPath);
      if (!stat.isFile()) {
        throw new UndoError(EXPIRED_UNDO_ERROR);
      }
    } catch {
      throw new UndoError(EXPIRED_UNDO_ERROR);
    }

    return {
      backupPath: record.backupPath,
      collectionPath: record.collectionPath,
    };
  }

  /**
   * Remove an undo record (e.g., after successful undo or on cleanup).
   *
   * @param undoId The opaque undo ID.
   */
  remove(undoId: string): void {
    this._store.delete(undoId);
  }

  /**
   * Clear all undo records (used on app shutdown).
   */
  clear(): void {
    this._store.clear();
  }

  /**
   * Internal: get a valid (non-expired, non-consumed, matching) undo record.
   *
   * @param undoId The opaque undo ID.
   * @param selectionId The opaque selection ID to match against.
   * @returns The UndoRecord.
   * @throws {UndoError} if the undo ID is unknown, expired, mismatched,
   *   or already consumed.
   */
  private _getValid(undoId: string, selectionId: string): UndoRecord {
    const record = this._store.get(undoId);
    if (!record) {
      throw new UndoError(EXPIRED_UNDO_ERROR);
    }

    // Check TTL.
    const age = this._clock.now() - record.createdAt;
    if (age > UNDO_TTL_MS) {
      this._store.delete(undoId);
      throw new UndoError(EXPIRED_UNDO_ERROR);
    }

    // Check one-shot consumption.
    if (record.consumed) {
      throw new UndoError(EXPIRED_UNDO_ERROR);
    }

    // Check selection binding.
    if (record.selectionId !== selectionId) {
      throw new UndoError(
        "This undo operation does not match the current selection."
      );
    }

    return record;
  }
}
